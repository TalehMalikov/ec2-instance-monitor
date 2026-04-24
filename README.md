# EC2 Instance Monitor

A real-time EC2 instance monitoring system built with AWS messaging services. Tracks instances in an Auto Scaling group and displays their status on a static webpage.

---

## Architecture

```
EC2 Auto Scaling → SNS → SQS → ec2_monitor.py → DynamoDB → instances.txt → S3 Webpage
```

| Component | Role |
|---|---|
| **Auto Scaling Group** | Automatically launches/terminates EC2 instances |
| **SNS** | Broadcasts launch/termination events |
| **SQS** | Queues notifications reliably for processing |
| **ec2_monitor.py** | Polls SQS, updates DynamoDB, writes `instances.txt` |
| **DynamoDB** | Persistent store of all instance states |
| **S3** | Hosts the static webpage and `instances.txt` |

The key idea is **decoupling** — the Auto Scaling group doesn't talk to the monitoring app directly. It fires an event, and the monitor processes it whenever ready. This makes the system reliable: if the monitor goes down, messages wait safely in SQS and nothing is lost.

---

## Prerequisites

- AWS CLI configured with valid credentials
- Python 3 with `boto3` installed
- An EC2 key pair

---

## AWS Resources Required

The following resources need to be provisioned before running the monitor:

- **EC2 Auto Scaling Group** — manages the instances being monitored
- **SNS Topic** — receives notifications from Auto Scaling
- **SQS Queue** — subscribes to SNS and stores messages
- **DynamoDB Table** — stores instance state (id, IP, hostname, etc.)
- **S3 Bucket** — hosts the static webpage

---

## Part A — Monitor Script

### Usage

```bash
python ec2_monitor.py \
  --queue <SQS_QUEUE_NAME> \
  --table <DYNAMODB_TABLE_NAME> \
  --bucket <S3_BUCKET_NAME>
```

### What it does

1. Connects to SQS and long-polls for up to 10 messages every 20 seconds
2. For each message:
   - **Launch event** → adds instance record to DynamoDB
   - **Termination event** → marks instance as terminated in DynamoDB
   - Deletes the message from the queue
3. Scans DynamoDB and writes all instance data to `instances.txt` in S3

### Expected output

```
Connecting to SQS queue ... and DynamoDB table ...
Long-polling and asking SQS for up to 10 messages...
Received 2 messages.
Processing message for instance launch
Deleting message...
```

### Verify

```bash
aws s3 cp s3://<your-bucket>/instances.txt -
```

---

## Part B — Webpage Console

A static webpage served from S3 that reads `instances.txt` every 10 seconds and displays instance status in a table.

### Setup

**1. Copy website files to your S3 bucket:**
```bash
aws s3 cp s3://mpcs-resources/mpcs_ec2_monitor_website s3://<your-bucket>/ --recursive
```

**2. Enable Static Website Hosting:**
- S3 → your bucket → Properties → Static website hosting → Enable
- Set index document to `index.html`

**3. Set bucket policy for public read access:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": {"AWS": "*"},
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::<your_bucket_name>/*"
    }
  ]
}
```

**4. Access the webpage:**
```
http://<your-bucket>.s3-website-us-east-1.amazonaws.com
```

> The monitor script must be running for the webpage to reflect current instance state.

---

## Triggering Events

Only instances managed by the Auto Scaling group send SQS notifications. To trigger a message, adjust the **Desired capacity** in the Auto Scaling group — do not manually launch or terminate instances from the EC2 console as those won't generate any notifications.

---

## Limitations

This system only monitors instances that are part of the Auto Scaling group. To monitor all EC2 instances regardless of how they were launched, use **Amazon EventBridge** with an EC2 state-change rule:

```json
{
  "source": ["aws.ec2"],
  "detail-type": ["EC2 Instance State-change Notification"]
}
```

This would capture every instance state change across your entire AWS account.