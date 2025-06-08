import aws_cdk as cdk

from utils.utils import Utility


class CustomSynthesizer:

    @staticmethod
    def build_synthesizer(env_profile: str, target_region: str):
        """
        Build Custom CDK Synthesizer for a specific target region using an INI-style properties file.

        @param env_profile: The environment profile (e.g., "develop") to load properties for.
                           This determines the filename: "resources/application.{env_profile}.properties".
        @param target_region: The AWS region for which to build the synthesizer (e.g., "eu-central-1").
        @return: aws_environment (cdk.Environment), cdk_synthesizer (cdk.DefaultStackSynthesizer)
        """
        properties_file_path = f"resources/application.{env_profile}.properties"
        all_props = Utility.load_properties(properties_file_path)

        if not all_props:
            raise ValueError(f"Failed to load properties from {properties_file_path}. File might be empty or not found.")

        cdk_settings_config = all_props.get('cdk_settings')
        if cdk_settings_config is None: # Check for None explicitly, as an empty dict is falsy but could be valid if empty section
            raise ValueError(f"Section [cdk_settings] is missing in {properties_file_path}")

        region_specific_config = all_props.get(target_region, {})
        # If region_specific_config is empty, it means no overrides for this region, or the section is missing.
        # This is acceptable if all required values are in [cdk_settings] or defaults.

        # Merge configurations: region-specific overrides cdk_settings.
        # Also, add current_target_region to the merged_config for easy access by stacks.
        merged_config = {**cdk_settings_config, **region_specific_config, 'current_target_region': target_region}

        # Populate Utility.cdk_custom_configs with the merged configuration for the current region
        Utility.cdk_custom_configs = merged_config

        # Validate required keys for the synthesizer and AWS environment
        required_keys_map = {
            'stack_deploy_account': "Deployment account ID",
            'stack_deploy_region': "Deployment AWS region",
            'bootstrap_cloudformation_role_arn': "CloudFormation execution role ARN",
            'bootstrap_deploy_role_arn': "Deployment action role ARN",
            'bootstrap_file_asset_publishing_role_arn': "File asset publishing role ARN",
            'bootstrap_lookup_role_arn': "Lookup role ARN",
            'bootstrap_file_assets_bucket_name': "File assets S3 bucket name"
        }

        missing_keys_details = []
        for key, description in required_keys_map.items():
            if not merged_config.get(key):
                missing_keys_details.append(f"'{key}' ({description})")
        
        if missing_keys_details:
            raise ValueError(
                f"Missing required configuration values in properties file '{properties_file_path}' "
                f"for target region '{target_region}'. Ensure these are defined in section '[{target_region}]' "
                f"or as defaults in '[cdk_settings]': {', '.join(missing_keys_details)}"
            )

        # Ensure stack_deploy_region from config matches target_region parameter for consistency
        config_deploy_region = merged_config.get('stack_deploy_region')
        if config_deploy_region != target_region:
            raise ValueError(
                f"Configuration inconsistency for target region '{target_region}': "
                f"The 'stack_deploy_region' found in properties ('{config_deploy_region}') "
                f"must match the 'target_region' parameter ('{target_region}') passed to build_synthesizer. "
                f"Please check section '[{target_region}]' or '[cdk_settings]' in '{properties_file_path}'."
            )

        aws_environment = cdk.Environment(
            account=merged_config['stack_deploy_account'],
            region=merged_config['stack_deploy_region'] # This is now validated to be === target_region
        )

        cdk_synthesizer = cdk.DefaultStackSynthesizer(
            qualifier=merged_config.get('bootstrap_qualifier', merged_config.get('synthesizer')),
            cloud_formation_execution_role=merged_config['bootstrap_cloudformation_role_arn'],
            deploy_role_arn=merged_config['bootstrap_deploy_role_arn'],
            file_asset_publishing_role_arn=merged_config['bootstrap_file_asset_publishing_role_arn'],
            image_asset_publishing_role_arn=merged_config.get('bootstrap_image_asset_publishing_role_arn'), # Optional
            lookup_role_arn=merged_config['bootstrap_lookup_role_arn'],
            file_assets_bucket_name=merged_config['bootstrap_file_assets_bucket_name'],
            image_assets_repository_name=merged_config.get('bootstrap_image_assets_repository_name'), # Optional
            bootstrap_stack_version_ssm_parameter=merged_config.get(
                'bootstrap_cdk_version_ssm_param_path',
                '/swift/cdk-bootstrap/version' # Retain previous custom default
            )
        )
        return aws_environment, cdk_synthesizer
