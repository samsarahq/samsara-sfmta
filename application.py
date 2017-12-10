#! /bin/python
#
# --- Samsara // SFMTA integration ---
#
# Contact support@samsara.com with any issues or questions
#
#
# Notes on logging:
# - Implemented logging using Python's logging module
# - Info level messages are logged for most function entrances and exits
# - Did not implement these messages for functions that are called in the the ThreadPool
#
# Notes on exception handling
# - API requests are wrapped in try/catch blocks
# - any exception that occurs is logged as a warning
# - in the event of an exception we retry the request for MAX_RETRIES attempts
# - in the event we reach MAX_RETRIES, an error email is sent, and we log as an error
#
# Notes on error emails
# - error emails are sent via the parameters set in the following environment variables
# --- SFMTA_ERROR_FROM_EMAIL, SFMTA_ERROR_TO_EMAIL, SFMTA_ERROR_FROM_PASSWORD
# - error emails are sent at most once for every ERROR_EMAIL_DELAY
# --- this is to avoid repeated emails in the case of a persistent failure

##############################
#
#         Imports
#
##############################

import boto3
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
import smtplib
import sys
import time
import traceback
import urllib

application = Flask(__name__)

if 'SFMTA_DEBUG' in os.environ and os.environ['SFMTA_DEBUG'] == '1':
	application.debug = True
	SFMTA_URL = 'https://stageservices.sfmta.com/shuttle/api'
else:
	SFMTA_URL = 'https://services.sfmta.com/shuttle/api'

s3 = boto3.resource('s3', region_name = 'us-west-2')

##############################
# Config variables
##############################

VEHICLE_SHEETS_JSON_URL = 'https://spreadsheets.google.com/feeds/list/' + os.environ['SFMTA_VEHICLE_GOOGLE_SHEETS_KEY'] + '/od6/public/values?alt=json'
SAMSARA_LOCATIONS_URL = 'https://api.samsara.com/v1/fleet/locations?access_token=' + os.environ['SAMSARA_SFMTA_API_TOKEN']
FREQUENCY = 5 # SFMTA requires GPS ping frequency of once every 5 seconds
DISTANCE_THRESHOLD = 50 # Consider vehicle is at a SFMTA Allowed Stop if less than 50 meters away from it
SAMSARA_SFMTA_S3 = os.environ['SAMSARA_SFMTA_S3_BUCKET']

##############################
# Global variables
##############################

vehicle_ids = set()
placards = {}
license_plates = {}
vehicle_names = {}

vehicle_lat = {}
vehicle_long = {}
vehicle_onTrip = {}
vehicle_timestamp_ms = {}

##############################
# Helper functions
##############################

# Great Circle Distance between two lat/longs
def distance(origin_lat, origin_long, dest_lat, dest_long):
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


# Gets vehicle info from a Google Sheet, and updates global variables
def get_vehicle_details(url):
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

# Pull SFMTA Allowed Stops and store in S3
@application.route('/get_sfmta_stops', methods=['GET', 'POST'])
def get_sfmta_stops():
	headers = {'accept': 'application/json', 'content-type': 'application/json'}
	r = requests.get(SFMTA_URL+'/AllowedStops', headers = headers)
	s3.Object(SAMSARA_SFMTA_S3,'allowed_stops.json').put(Body=r.text)
	return "SFMTA Allowed Stops updated"

#Healthcheck URL for AWS
@application.route('/admin/healthcheck')
def healthcheck():
    return "Hello World!" 

# Get all vehicle telematics data from Samsara
def get_all_vehicle_data():

	get_vehicle_details(VEHICLE_SHEETS_JSON_URL)

	group_payload = { "groupId" : int(os.environ['SAMSARA_SFMTA_GROUP_ID']) }

	r = requests.post(SAMSARA_LOCATIONS_URL, data = json.dumps(group_payload))

	if r.status_code != 200:
		print 'Samsara API returned error - ' + str(r.status_code)
		print r.text
		print 'Continuing loop'

	else:

		locations_json = r.json()

		for vehicle in locations_json['vehicles']:
			vehicle_id = str(vehicle['id']).decode("utf-8")
			vehicle_lat[vehicle_id] = vehicle['latitude']
			vehicle_long[vehicle_id] = vehicle['longitude']
			vehicle_onTrip[vehicle_id] = vehicle['onTrip']

	return

# Push all vehicle data to SFMTA
def push_all_vehicle_data(current_time):

	num_vehicles = len(vehicle_ids)
	pool = ThreadPool(num_vehicles)

	pool.map(push_vehicle_data_star, itertools.izip(vehicle_ids,itertools.repeat(current_time)))

	pool.close()
	pool.join()

	return

def push_vehicle_data_star(vehicle_data):
	#"""Convert `f([1,2])` to `f(1,2)` call."""
	return push_vehicle_data(*vehicle_data)

# Check if a location is near one of the SFMTA AllowedStops - if yes, return the stop ID, else return 9999
def find_stop_id(stop_lat, stop_long):
	allowed_stops_object = s3.Object(SAMSARA_SFMTA_S3,'allowed_stops.json')
	allowed_stops_json = json.loads(allowed_stops_object.get()['Body'].read().decode('utf-8'))

	closest_stop_id = 9999
	min_distance = 99999

	for stop in allowed_stops_json['Stops']['Stop']:
		current_stop_id = stop['StopId']
		current_stop_lat = stop['StopLocationLatitude']
		current_stop_long = stop['StopLocationLongitude']

		curr_distance = distance(current_stop_lat,current_stop_long,stop_lat,stop_long)

		if(curr_distance < min_distance):
			min_distance = curr_distance
			closest_stop_id = current_stop_id

	if (min_distance <= DISTANCE_THRESHOLD ):
		stop_id = closest_stop_id
	else:
		stop_id = 9999

	return stop_id

# Push data for a specific vehicle to SFMTA
def push_vehicle_data(vehicle_id, current_time):
	# Pull location data for vehicle_id at current_time and send to SFMTA

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

	sfmta_payload_json = json.dumps(sfmta_payload)

	sfmta_telemetry_url = SFMTA_URL + '/Telemetry/'

	headers = {'content-type': 'application/json'}

	r = requests.post(sfmta_telemetry_url, data = sfmta_payload_json, auth= (os.environ['SFMTA_USERNAME'], os.environ['SFMTA_PASSWORD']), headers = headers )
	
	if r.status_code != 200:
		print 'Error pushing data to SFMTA for vehicle = ' + str(vehicle_id)
		print r.text
		print 'Continuing loop'
	else:
		if r.json()['Success'] != 'True':
			print 'Error pushing data to SFMTA for vehicle = ' + str(vehicle_id)
			print r.json()
			print 'Continuing loop'

	return

# Infinite loop that pulls & pushes data every 5 seconds - this is called once in a cron job at a specific time (when system is activated)
# If any errors are generated, emails are sent to Samsara
@application.route('/push_sfmta')
def push_all_data():
	try:

		time.tzset()

		print 'Started push to SFMTA'

		while True:
			
			start_time = time.time()
			current_time = start_time

			# print 'Processing loop for time = ' + str(current_time)

			get_all_vehicle_data()

			samsara_api_time = time.time() - start_time

			# print 'Samsara API time taken = '+ str(samsara_api_time)

			push_all_vehicle_data(current_time)

			end_time = time.time()

			timeSpent = end_time - start_time
			# print 'Total time taken = '+ str(timeSpent)
			timeToWait = FREQUENCY - timeSpent

			if timeToWait >= 0:
				time.sleep(timeToWait)

			# print 'Completed processing loop for time = ' + str(current_time)

		return "Success"

	except:

		email_body = "There was an error sending data to SFMTA - please check logs\n\n"
		email_subject = "Error sending data to SFMTA"
		formatted_lines = traceback.format_exc().splitlines()
		for j in formatted_lines:
			email_body += j
		message = 'Subject: %s\n\n%s' % (email_subject, email_body)

		from_email = os.environ['SFMTA_ERROR_FROM_EMAIL']
		to_email = os.environ['SFMTA_ERROR_TO_EMAIL']

		s = smtplib.SMTP('smtp.gmail.com')
		s.set_debuglevel(1) 
		s.ehlo() 
		s.starttls() 
		s.login(from_email, os.environ['SFMTA_ERROR_FROM_PASSWORD'])

		# Send email and close the connection
		s.sendmail(from_email, to_email, message)
		s.quit()

		return "There was an error sending data to SFMTA"


if __name__ == '__main__':
        if 'SFMTA_LOCALHOST' in os.environ and os.environ['SFMTA_LOCALHOST'] == '1':
                application.run(use_reloader=False)
        else:
                application.run('0.0.0.0')
