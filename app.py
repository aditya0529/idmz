#!/usr/bin/env python3

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks, NagSuppressions
from utils.utils import Utility
from synth.CustomSynthesizer import CustomSynthesizer
from global_apigw.global_apigw_stack import GlobalAPIGWStack
from global_apigw.idmz_network_stack import IDMZNetworkStack
import os

# from python.s3_certificates import s3forCerts

app = cdk.App()

# Get the SW ENVIRONMENT from CDK Context. If none provided, Default: dev
sw_env = os.getenv("SRC_BRANCH", "develop") or os.getenv("SRC_BRANCH", "qa") or os.getenv("SRC_BRANCH", "live")
print(f"Deplyment Env : {sw_env}")

# Pass the SW Environment to setup custom synthesizer and AWS os.getenv("SRC_BRANCH", "develop")environment
aws_environment, custom_cdk_synthesizer = CustomSynthesizer.build_synthesizer(
    sw_env)

# s3forCerts(app, "S3TemplateStack", env={'region': 'us-east-1'})
idmz_network_stack = IDMZNetworkStack(app,
                                      "IDMZ-Network-Stack",
                                      synthesizer=custom_cdk_synthesizer,
                                      env=aws_environment)
GlobalAPIGWStack(app,
                 "iDMZ-APIGateway-HTTP-API",
                 synthesizer=custom_cdk_synthesizer,
                 env=aws_environment,
                 vpc=idmz_network_stack.vpc,
                 sg_vpclink=idmz_network_stack.sg_vpclink,
                 sg_vpce=idmz_network_stack.sg_vpce,
                 sg_nlb=idmz_network_stack.sg_nlb)

cdk_custom_configs = Utility.cdk_custom_configs

# Apply tags to stack recursively
tags = {
    'sw:owner': cdk_custom_configs['owner'],
    'sw:application': cdk_custom_configs['workload']
}
for key, value in tags.items():
    cdk.Tags.of(app).add(key, value)

# Inspect stack with cdk-nag before synth
cdk.Aspects.of(app).add(AwsSolutionsChecks())

app.synth()
