#!/usr/bin/env python3

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks # NagSuppressions can be added if needed
from utils.utils import Utility
from synth.CustomSynthesizer import CustomSynthesizer
from global_apigw.global_apigw_stack import GlobalAPIGWStack
from global_apigw.idmz_network_stack import IDMZNetworkStack
import os

app = cdk.App()

# Determine the environment profile (e.g., "develop", "qa", "live")
# Prioritize CDK_ENV_PROFILE, then SRC_BRANCH, default to "develop"
env_profile = os.getenv("CDK_ENV_PROFILE")
if not env_profile:
    src_branch_env = os.getenv("SRC_BRANCH")
    if src_branch_env in ["qa", "live"]: # Explicitly map known branch names to profiles
        env_profile = src_branch_env
    else: # Default for "develop", feature branches, or undefined SRC_BRANCH
        env_profile = "develop"
print(f"Deployment Environment Profile: {env_profile}")

# Load all properties for the determined environment profile
properties_file_path = f"resources/application.{env_profile}.properties"
all_props = Utility.load_properties(properties_file_path)

if not all_props or 'cdk_settings' not in all_props:
    raise ValueError(f"Failed to load properties or [cdk_settings] missing in {properties_file_path}")

cdk_global_settings = all_props['cdk_settings']

# Get target regions from cdk_settings
target_regions_str = cdk_global_settings.get('target_regions')
if not target_regions_str:
    raise ValueError(f"'target_regions' not defined in [cdk_settings] in {properties_file_path}")

target_regions = [region.strip() for region in target_regions_str.split(',') if region.strip()]
if not target_regions:
    raise ValueError(f"'target_regions' is empty or invalid in [cdk_settings] in {properties_file_path}")

print(f"Target regions for deployment: {target_regions}")

for region in target_regions:
    print(f"--- Synthesizing for region: {region} ---")
    # Build synthesizer for the current target region.
    # This call is crucial as it sets Utility.cdk_custom_configs for the current region.
    aws_environment, custom_cdk_synthesizer = CustomSynthesizer.build_synthesizer(
        env_profile, region
    )
    
    # Utility.cdk_custom_configs is now populated by build_synthesizer with merged
    # global and region-specific settings for the current 'region'.

    idmz_network_stack_id = f"IDMZ-Network-Stack-{region}"
    idmz_network_stack = IDMZNetworkStack(app,
                                          idmz_network_stack_id,
                                          synthesizer=custom_cdk_synthesizer,
                                          env=aws_environment)

    global_apigw_stack_id = f"iDMZ-APIGateway-HTTP-API-{region}"
    GlobalAPIGWStack(app,
                     global_apigw_stack_id,
                     synthesizer=custom_cdk_synthesizer,
                     env=aws_environment,
                     vpc=idmz_network_stack.vpc,
                     sg_vpclink=idmz_network_stack.sg_vpclink,
                     sg_vpce=idmz_network_stack.sg_vpce,
                     sg_nlb=idmz_network_stack.sg_nlb,
                     vpce_subnets=idmz_network_stack.vpce_subnets,
                     nlb_subnets=idmz_network_stack.nlb_subnets,
                     vpclink_subnets=idmz_network_stack.vpclink_subnets)
    
    # Region-specific tags can be applied here if needed, using Utility.cdk_custom_configs
    # For example:
    # current_region_config = Utility.cdk_custom_configs
    # cdk.Tags.of(idmz_network_stack).add('sw:region_specific_tag', current_region_config.get('some_regional_value'))
    # cdk.Tags.of(GlobalAPIGWStack_instance).add('sw:region_specific_tag', current_region_config.get('some_regional_value'))

# Apply global tags to all stacks in the app
# These tags should ideally come from non-region-specific settings (e.g., [cdk_settings])
# or be truly global.
global_tags = {
    'sw:owner': cdk_global_settings.get('owner', 'default-owner'), # Use .get for safety
    'sw:application': cdk_global_settings.get('workload', 'default-workload'), # Use .get for safety
    'sw:environment_profile': env_profile
}
for key, value in global_tags.items():
    if value: # Ensure value is not None or empty before adding tag
        cdk.Tags.of(app).add(key, value)

# Inspect all stacks with cdk-nag before synth
cdk.Aspects.of(app).add(AwsSolutionsChecks(verbose=True)) # Added verbose for more detailed output

# Add NagSuppressions if needed, for example:
# NagSuppressions.add_stack_suppressions(idmz_network_stack_instance_for_region_A, [{"id": "AwsSolutions-VPC7", "reason": "Description"}])
# NagSuppressions.add_resource_suppressions_by_path(stack, path_to_resource, [{"id": "RuleID", "reason": "Reason"}])

app.synth()
