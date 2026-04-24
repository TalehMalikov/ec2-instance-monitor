# ec2_monitor.py
#
# Copyright (C) 2011-2017 Vas Vasiliadis
# University of Chicago
#
# Adapted from  "Using Dynamic Registration and Dashboards
# for Amazon EC2 Instances", by Amazon Web Services, 2014-2015
#
##
__author__ = "Vas Vasiliadis <vas@uchicago.edu>"

import boto3
import json
import time
import sys
import getopt
import argparse

# Set region
REGION = "us-east-1"


def main(argv=None):
    """Connect to SQS and poll for messages."""

    # Handle command-line arguments for AWS credentials and resource names
    parser = argparse.ArgumentParser(
        description="Process AWS resources and credentials."
    )
    parser.add_argument(
        "--queue",
        action="store",
        dest="sqs_queue_name",
        required="true",
        help="SQS queue for storing AutoScaling notification messages",
    )
    parser.add_argument(
        "--table",
        action="store",
        dest="db_table_name",
        required="true",
        help="DynamoDB table where instance information is stored",
    )
    parser.add_argument(
        "--bucket",
        action="store",
        dest="s3_output_bucket",
        required="true",
        help="S3 bucket where list of instances will be stored",
    )
    parser.add_argument(
        "--key",
        action="store",
        dest="s3_output_key",
        default="instances.txt",
        help="S3 key where list of instances will be stored",
    )
    args = parser.parse_args()

    # Set queue names
    sqs_queue_name = args.sqs_queue_name
    db_table_name = args.db_table_name

    # Get S3 bucket and object
    s3_output_bucket = args.s3_output_bucket
    s3_output_key = args.s3_output_key

    print(
        f"Connecting to SQS queue {sqs_queue_name} and DynamoDB table {db_table_name}"
    )

    # Connect to SQS and get queue (code below assumes a boto3 SQS resource)
    # cf. https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs.html#service-resource
    sqs = boto3.resource('sqs', region_name=REGION)
    queue = sqs.get_queue_by_name(QueueName=sqs_queue_name)

    while True:
        print("Long-polling and asking SQS for up to 10 messages...")
        # Get messages
        messages  = queue.receive_messages(
            WaitTimeSeconds=20,
            MaxNumberOfMessages=10
        )

        if len(messages) > 0:   # may need to change for boto3 SQS client
            print(f"Received {str(len(messages))} messages.")   # may need to change for boto3 SQS client

            # Iterate each message
            for message in messages:   # may need to change for boto3 SQS client
                # Parse JSON message
                msg_body = json.loads(json.loads(message.body)["Message"])

                # Trap the EC2_INSTANCE_LAUNCH event
                if msg_body["Event"] == "autoscaling:EC2_INSTANCE_LAUNCH":
                    print("Processing message for instance launch")
                    launch_instance(msg_body["EC2InstanceId"], db_table_name)

                # Trap the EC2_INSTANCE_TERMINATE event
                elif msg_body["Event"] == "autoscaling:EC2_INSTANCE_TERMINATE":
                    print("Processing message for instance termination")
                    terminate_instance(msg_body["EC2InstanceId"], db_table_name)

                # Delete the message from the queue
                print("Deleting message...")
                response = message.delete()

            # Get instance data from database into JSON string
            instances_json = db_instances_to_json(db_table_name)

            # Write JSON string to S3
            write_instances_to_s3(instances_json, s3_output_bucket, s3_output_key)


def get_instance(instance_id):
    """Locate an instance by its ID."""

    # Connect to EC2
    ec2 = boto3.resource("ec2", region_name=REGION)

    # Find an instance by its ID
    instance = ec2.Instance(id=instance_id)

    return instance


def launch_instance(instance_id, db_table_name):
    """Connect to DynamoDB and register instance info."""

    instance = get_instance(instance_id)

    # Connect to DynamodB and get table
    db = boto3.resource("dynamodb", region_name=REGION)
    table = db.Table(db_table_name)

    # Create a new record for this instance
    data = {
        "InstanceId": instance_id,
        "pub_hostname": instance.public_dns_name,
        "pub_ip": instance.public_ip_address,
        "priv_hostname": instance.private_dns_name,
        "priv_ip": instance.private_ip_address,
        "ami_id": instance.image_id,
        "availability_zone": instance.placement["AvailabilityZone"],
        "terminated": "false",
    }

    # Save the item to DynamoDB
    table.put_item(Item=data)


def terminate_instance(instance_id, db_table_name):
    """Connect to DynamoDB and remove a registered instance."""

    # Connect to DynamodB and get table
    db = boto3.resource("dynamodb", region_name=REGION)
    table = db.Table(db_table_name)

    # Get the item to soft delete
    item = table.update_item(
        Key={"InstanceId": instance_id},
        ExpressionAttributeNames={"#terminated": "terminated"},
        UpdateExpression="SET #terminated = :t",
        ExpressionAttributeValues={":t": "true"},
    )


def db_instances_to_json(db_table_name):
    """Query DynamoDB for running instances; write output to a JSON string."""

    # Connect to DynamodB (using key from env) and get table
    db = boto3.resource("dynamodb", region_name=REGION)
    table = db.Table(db_table_name)

    # Select all items from the table
    items = table.scan()  # needed here; otherwise avoid using scan()!

    # List the fields we're interested in
    fields = [
        "terminated",
        "ami_id",
        "availability_zone",
        "pub_ip",
        "pub_hostname",
        "priv_ip",
        "priv_hostname",
    ]

    json_string = '{ "instances" : ['

    # Iterate over the ResultSet and write out items in json format
    for item in items["Items"]:
        json_string += '{"id" : "' + item["InstanceId"] + '",'
        for field in fields:
            json_string += '"' + field + '" : "' + item[field] + '",'
        json_string += "},"

    # Finish the JSON string and hackily handle the closing brackets-comma issue
    json_string += "] }"
    json_string = json_string.replace(",]", "]")
    json_string = json_string.replace(",}", "}")

    return json_string


def write_instances_to_s3(instances_json, s3_output_bucket, s3_output_key):
    """Write instances string to S3."""

    # Connect to S3 and get the output bucket
    s3 = boto3.resource("s3")
    output_bucket = s3.Bucket(s3_output_bucket)

    # Store the instances_json text as an S3 object
    s3.Object(s3_output_bucket, s3_output_key).put(Body=instances_json)


if __name__ == "__main__":
    sys.exit(main())

### EOF