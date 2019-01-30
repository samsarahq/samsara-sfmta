# SFMTA - Samsara Integration

Please contact support@samsara.com for more details

## Setup / Configuration

[Install the AWS EB CLI](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/eb-cli3-install.html#eb-cli3-install.cli-only)
`brew install awsebcli`

Clone this repository
`git clone https://github.com/samsarahq/samsara-sfmta.git`

Navigate to the project directory
`cd samsara-sfmta`

Initialize an Elastic Beanstalk project
`eb init`

Follow the prompts, see example:

```{bash}
Select a default region
1) us-east-1 : US East (N. Virginia)
2) us-west-1 : US West (N. California)
3) us-west-2 : US West (Oregon)
4) eu-west-1 : EU (Ireland)
5) eu-central-1 : EU (Frankfurt)
6) ap-south-1 : Asia Pacific (Mumbai)
7) ap-southeast-1 : Asia Pacific (Singapore)
8) ap-southeast-2 : Asia Pacific (Sydney)
9) ap-northeast-1 : Asia Pacific (Tokyo)
10) ap-northeast-2 : Asia Pacific (Seoul)
11) sa-east-1 : South America (Sao Paulo)
12) cn-north-1 : China (Beijing)
13) cn-northwest-1 : China (Ningxia)
14) us-east-2 : US East (Ohio)
15) ca-central-1 : Canada (Central)
16) eu-west-2 : EU (London)
17) eu-west-3 : EU (Paris)
(default is 3): 3

Select an application to use
1) some-app-name
2) some-other-app-name
3) [ Create new Application ]
(default is 3): 3

Enter Application Name
(default is "samsara-sfmta"): samsara-sfmta
Application samsara-sfmta has been created.

It appears you are using Python. Is this correct?
(Y/n): y

Select a platform version.
1) Python 3.6
2) Python 3.4
3) Python 3.4 (Preconfigured - Docker)
4) Python 2.7
5) Python
(default is 1): 4

Note: Elastic Beanstalk now supports AWS CodeCommit; a fully-managed source control service. To learn more, see Docs: https://aws.amazon.com/codecommit/
Do you wish to continue with CodeCommit? (y/N) (default is n): n

Do you want to set up SSH for your instances?
(Y/n): Y

Select a keypair.
1) some-keypair
2) some-other-keypair
3) [ Create new KeyPair ]
(default is 2): 3

Type a keypair name.
(Default is aws-eb): aws-eb
Generating public/private rsa key pair.

Enter passphrase (empty for no passphrase): 
Enter same passphrase again: 
Your identification has been saved in /Users/ericshreve/.ssh/aws-eb.
Your public key has been saved in /Users/ericshreve/.ssh/aws-eb.pub.
The key fingerprint is:
SHA256: ******************* aws-eb
The key's randomart image is:
+---[RSA 2048]----+
|                 |
|                 |
|                 |
|                 |
|                 |
|                 |
|                 |
|                 |
|                 |
+----[SHA256]-----+
WARNING: Uploaded SSH public key for "aws-eb" into EC2 for region us-west-2.
```

Create the application
`eb create`

Follow the prompts:

```{bash}
Enter Environment Name
(default is samsara-sfmta-dev): samsara-sfmta-dev
Enter DNS CNAME prefix
(default is samsara-sfmta-dev): samsara-sfmta-dev

Select a load balancer type
1) classic
2) application
3) network
(default is 1): 1

Creating application version archive "app-ae30-190130_014607".
Uploading samsara-sfmta/app-ae30-190130_014607.zip to S3. This may take a while.
Upload Complete.
```

## AWS Configuration

### Elastic Beanstalk Console

- Select the application
- Click on the Environment
- Click on "Configuration" in the left hand sidebar
- Under "Software" click "Modify"
- Enter the values for the Environment variables
- Click "Apply"

### EC2 Console

- Find the instance an check the box on the left hand side
- Scroll down to Description > Security groups and note the name of the group
- On the left hand side under "Network and Security" click Security Groups
- Find the security group we noted earlier
- Click "Inbound" and then "Edit"
- Configure one rule: SSH, Port 22, "My IP"
- Go back to the list of instances and select the correct one
- Click "Connect", copy the example to a text editor

## On your Local machine

Prepare your SSH key
`cd .ssh`
`mv aws-eb aws-eb.pem`
`chmod 400 aws-eb.pem`

Navigate back to the project directory
`cd ~/samsara-sfmta`

SSH to the EC2 instance, edit the example ssh command that you copied at the end
of AWS configuration
`ssh -i "/path/to/private/ssh/key" ec2-user@ec2-34-220-158-35.us-west-2.compute.amazonaws.com`

Run healthcheck command
`curl http://localhost/admin/healthcheck`

Start the data push
`curl http://localhost/push_sfmta`