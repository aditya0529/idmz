import aws_cdk as core
import aws_cdk.assertions as assertions

from sw_devhub_idmz_appinfra_code_main_aws.sw_devhub_idmz_appinfra_code_main_aws_stack import SwDevhubIdmzAppinfraCodeMainAwsStack

# example tests. To run these tests, uncomment this file along with the example
# resource in sw_devhub_idmz_appinfra_code_main_aws/sw_devhub_idmz_appinfra_code_main_aws_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = SwDevhubIdmzAppinfraCodeMainAwsStack(app, "sw-devhub-idmz-appinfra-code-main-aws")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
