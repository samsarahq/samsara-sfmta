#! /bin/python
#
# --- Samsara // SFMTA integration ---
#
# Contact support@samsara.com with any issues or questions
#
# Usage:
# 	- Confirm that all environment variables have been configured
# 	- Start the application by running 'python application.py'
# 	- Start the data push by running 'curl -s http://localhost:5000/push_sfmta'
# 	- An error email will be sent if there are any uncaught Exceptions
from collections import OrderedDict
from flask import Flask, render_template, request, url_for, redirect
import itertools
import json
import logging
import math
from math import radians, cos, sin, asin, sqrt, atan2
from multiprocessing.dummy import Pool as ThreadPool 
import os
import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from requests.packages.urllib3.util.retry import Retry
import smtplib
import sys
import time
import traceback
import urllib

application = Flask(__name__)

VEHICLE_SHEETS_JSON_URL = 'https://spreadsheets.google.com/feeds/list/' + os.environ['SFMTA_VEHICLE_GOOGLE_SHEETS_KEY'] + '/od6/public/values?alt=json'
SAMSARA_LOCATIONS_URL = 'https://api.samsara.com/v1/fleet/locations?access_token=' + os.environ['SAMSARA_SFMTA_API_TOKEN']
FREQUENCY = 5				# SFMTA requires GPS ping frequency of once every 5 seconds
DISTANCE_THRESHOLD = 50		# Consider vehicle is at a SFMTA Allowed Stop if less than 50 meters away from it
ONE_DAY_IN_SECONDS = 86400

if 'SFMTA_DEBUG' in os.environ and os.environ['SFMTA_DEBUG'] == '1':
	application.debug = True
	SFMTA_URL = 'https://stageservices.sfmta.com/shuttle/api'
else:
	SFMTA_URL = 'https://services.sfmta.com/shuttle/api'

logging.basicConfig(filename = "sfmta.log",
					level = logging.ERROR,
					format="%(asctime)s:%(levelname)s:%(message)s")


##############################
#     Global Variables
##############################
vehicle_ids = set()
placards = {}
license_plates = {}
vehicle_names = {}

vehicle_lat = {}
vehicle_long = {}
vehicle_onTrip = {}
vehicle_timestamp_ms = {}

global sfmta_allowed_stops

##############################
#     Helper Functions
##############################
@application.route('/admin/healthcheck')
def healthcheck():
	return "Hello World!\n" 


def distance(origin_lat, origin_long, dest_lat, dest_long):
	""" Great Circle Distance between two lat/longs """
	radius = 6371 * 1000 # meters

	lat1 = origin_lat
	lon1 = origin_long

	lat2 = dest_lat
	lon2 = dest_long

	if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
		return 99999

	dlat = radians(lat2-lat1)
	dlon = radians(lon2-lon1)
	a = sin(dlat/2) * sin(dlat/2) + cos(radians(lat1)) \
		* cos(radians(lat2)) * sin(dlon/2) * sin(dlon/2)
	c = 2 * atan2(sqrt(a), sqrt(1-a))
	d = radius * c
	return d


def send_error_email(email_body, email_subject):
	logging.info("Starting send_error_email")
	formatted_lines = traceback.format_exc().splitlines()
	for j in formatted_lines:
		email_body += j
	message = 'Subject: %s\n\n%s' % (email_subject, email_body)

	from_email = os.environ['SFMTA_ERROR_FROM_EMAIL']
	to_email = os.environ['SFMTA_ERROR_TO_EMAIL']

	s = smtplib.SMTP('smtp.gmail.com', 587)
	s.ehlo() 
	s.starttls() 
	s.login(from_email, os.environ['SFMTA_ERROR_FROM_PASSWORD'])

	# Send email and close the connection
	s.sendmail(from_email, to_email, message)
	s.quit()
	logging.info("Finished send_error_email")


def get_vehicle_details(url):
	""" Gets vehicle info from a Google Sheet, and updates global variables """
	logging.info("Starting get_vehicle_details")
	try:
		response = urllib.urlopen(url)

		if response.getcode() != 200:
			print 'Google Sheet returned error - ' + str(response.getcode())
			print response.read()
			print 'Continuing loop'

		else:
			json_data = json.loads(response.read())

			vehicle_ids.clear()

			for entry in json_data['feed']['entry']:
				vehicle_id = entry['gsx$samsaradeviceid']['$t']
				vehicle_ids.add(vehicle_id)

				placards[vehicle_id] = entry['gsx$vehicleplacardnumber']['$t']
				license_plates[vehicle_id] = entry['gsx$licenseplatenumber']['$t']
				vehicle_names[vehicle_id] = entry['gsx$vehicleidname']['$t']
		logging.info("Finished get_vehicle_details")
		return "Success"
	except Exception as e:
		logging.warning("Error reading vehicle details from Google Sheet\n" + str(e))
		return "Error reading vehicle details from Google Sheet\n" + str(e)


def find_stop_id(stop_lat, stop_long):
	""" Check if a location is near one of the SFMTA AllowedStops - 
		if yes, return the stop ID, else return 9999 """
	try:
		closest_stop_id = 9999
		min_distance = 99999
		for stop in sfmta_allowed_stops:
			current_stop_id = stop['StopId']
			current_stop_lat = stop['StopLocationLatitude']
			current_stop_long = stop['StopLocationLongitude']

			curr_distance = distance(current_stop_lat, current_stop_long, stop_lat, stop_long)

			if(curr_distance < min_distance):
				min_distance = curr_distance
				closest_stop_id = current_stop_id

		if (min_distance <= DISTANCE_THRESHOLD ):
			stop_id = closest_stop_id
		else:
			stop_id = 9999
		return stop_id
	except Exception as e:
		return "Error in find_stop_id\n" + str(e)


##############################
#   Samsara API Functions
##############################
def get_all_vehicle_data():
	""" Get current telematics data for all vehicles """
	logging.info("Starting get_all_vehicle_data")
	try:
		get_vehicle_details(VEHICLE_SHEETS_JSON_URL)
		group_payload = { "groupId" : int(os.environ['SAMSARA_SFMTA_GROUP_ID']) }
		r = requests.post(SAMSARA_LOCATIONS_URL, data = json.dumps(group_payload))
		locations_json = r.json()
		for vehicle in locations_json['vehicles']:
			vehicle_id = str(vehicle['id']).decode("utf-8")
			vehicle_lat[vehicle_id] = vehicle['latitude']
			vehicle_long[vehicle_id] = vehicle['longitude']
			vehicle_onTrip[vehicle_id] = vehicle['onTrip']
		logging.info("Finished get_all_vehicle_data")
		return('Success')
	except Exception as e:
		logging.warning("Error pulling data from Samsara API\n" + str(e))
		return "Error pulling data from Samsara API\n" + str(e)


##############################
#    SFMTA API Functions
##############################
def build_sfmta_payload(vehicle_id, current_time):
	""" Build the payload to send to sfmta for the given vehicle and time """
	sfmta_payload = OrderedDict()

	sfmta_payload['TechProviderId'] = int(os.environ['SFMTA_TECH_PROVIDER_ID'])
	sfmta_payload['ShuttleCompanyId'] = os.environ['SFMTA_SHUTTLE_COMPANY_ID']
	sfmta_payload['VehiclePlacardNum'] = placards[vehicle_id]
	sfmta_payload['LicensePlateNum'] = license_plates[vehicle_id]

	if(vehicle_onTrip[vehicle_id] == True):
		vehicle_status = 1
		stop_id = 9999
	else:
		vehicle_status = 2
		stop_id = find_stop_id(vehicle_lat[vehicle_id], vehicle_long[vehicle_id])

	sfmta_payload['StopId'] = stop_id
	sfmta_payload['VehicleStatus'] = vehicle_status

	sfmta_payload['LocationLatitude'] = vehicle_lat[vehicle_id]
	sfmta_payload['LocationLongitude'] = vehicle_long[vehicle_id]
	sfmta_payload['TimeStampLocal'] = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(current_time))

	return sfmta_payload


def push_vehicle_data(vehicle_id, current_time):
	""" Build the payload, convert to json, push to the SFMTA API """
	sfmta_payload = build_sfmta_payload(vehicle_id, current_time)
	sfmta_payload_json = json.dumps(sfmta_payload)
	sfmta_telemetry_url = SFMTA_URL + '/Telemetry/'
	try:
		sess = requests.Session()
		sess.auth = HTTPBasicAuth(os.environ['SFMTA_USERNAME'], os.environ['SFMTA_PASSWORD'])
		sess.headers = None
		sess.headers = {'content-type': 'application/json'}

		retry = Retry(total = 5, backoff_factor = 1)
		adapter = HTTPAdapter(max_retries = retry)
		sess.mount('https://', adapter)
		r = sess.post(url = sfmta_telemetry_url, data = sfmta_payload_json)
		sess.close()
		if r.json()['Success'] != "True":
			raise Exception("POST to SFMTA was unsuccessful -- " + str(vehicle_id) + ' -- ' + str(current_time))
	
	except Exception as e:
		logging.warning('Error pushing data to SFMTA API -- ' + str(e) + '\n' + str(vehicle_id) + ' -- ' + str(current_time) + ' --\n' + json.dumps(sfmta_payload) + '\n--\n')
	

# unpacks the list passed to this function to arguments, and calls function
# Convert `f([1,2])` to `f(1,2)` call
def push_vehicle_data_star(vehicle_data):
	return push_vehicle_data(*vehicle_data)


def push_all_vehicle_data(current_time):
	""" Push all vehicle data to SFMTA in parallel """
	logging.info('Starting push_all_vehicle_data')

	num_vehicles = len(vehicle_ids)
	pool = ThreadPool(num_vehicles)

	logging.info('Mapping push_vehicle_data_star to each thread in the pool')
	pool.map(push_vehicle_data_star, itertools.izip(vehicle_ids,itertools.repeat(current_time)))
	logging.info('All threads finished executing push_vehicle_data')

	pool.close()
	pool.join()

	logging.info('Finished push_all_vehicle_data')
	return


def get_sfmta_stops():
	""" Pull SFMTA Allowed Stops and store local variable """
	headers = {'accept': 'application/json', 'content-type': 'application/json'}
	try:
		r = requests.get(SFMTA_URL+'/AllowedStops', headers = headers)
		stops = r.json()['Stops']['Stop']
		return stops
	except Exception as e:
		logging.warning("Error updating SFMTA Allowed Stops\n" + str(e))
		return "Error updating SFMTA Allowed Stops\n" + str(e)


##############################
#   Main Application Loop
##############################
@application.route('/push_sfmta')
def push_all_data():
	logging.info('Starting push_all_data')
	time.tzset()
	init_time = time.time()
	sfmta_allowed_stops = get_sfmta_stops()

	while True:
		try:
			start_time = time.time()
			current_time = start_time
			if current_time > (init_time + ONE_DAY_IN_SECONDS):
				sfmta_allowed_stops = get_sfmta_stops()
				init_time = current_time
				logging.info("SFMTA Allowed Stops have been Updated.")
			logging.info("Processing loop for time = " + str(current_time))

			# if the function fails then skip to next iteration of the loop
			if get_all_vehicle_data() != 'Success':
				continue

			samsara_api_time = time.time() - start_time
			logging.info("Samsara API time taken = "+ str(samsara_api_time))

			push_all_vehicle_data(current_time)

			end_time = time.time()
			time_spent = end_time - start_time
			logging.info("Total time taken for this iteration = " + str(time_spent))
			logging.info("Completed processing loop for time = " + str(current_time))

			time_to_wait = FREQUENCY - time_spent

			if time_to_wait >= 0:
				time.sleep(time_to_wait)
		except Exception as e:
			email_body = "There was an error sending data to SFMTA - please check logs\n\n"
			email_subject = "Error sending data to SFMTA"
			send_error_email(email_body, email_subject)
			logging.error('Error email sent at ' + str(time.time()))
			continue


if __name__ == '__main__':
	sfmta_allowed_stops = get_sfmta_stops()
	if 'SFMTA_LOCALHOST' in os.environ and os.environ['SFMTA_LOCALHOST'] == '1':
		application.run(use_reloader=False)
	else:
		application.run('0.0.0.0')