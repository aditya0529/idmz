import json


def lambda_handler(event, context):
    response = {
        "statusCode": 200,
        "headers": {
            "content-type": "application/json"
        },
        "body": json.dumps('idmzhealth=SUCCESS')
    }
    return response
