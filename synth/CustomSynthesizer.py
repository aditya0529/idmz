import aws_cdk as cdk

from utils.utils import Utility


class CustomSynthesizer:

    @staticmethod
    def build_synthesizer(sw_env):
        """
        Build Custom CDK Synthesizer
        @param sw_env: swift environment
        @return: aws environment, custom cdk synthesizer

        """
        cdk_custom_configs = \
            Utility.load_properties(
                "resources/application." + sw_env + ".properties")

        # Environment Properties optional properties provided but if no value prompt exception
        if not all(cdk_custom_configs.values()):
            raise ValueError(
                "Some Environment Properties are added in app.<ENV>.properties , but No valid values provided"
            )

            # AWS Account and Region to deployed should be specified, if not
            # prompt exception
        elif cdk_custom_configs.get(
                'stack_deploy_account') is None or cdk_custom_configs.get(
                    'stack_deploy_region') is None:
            raise ValueError(
                "Deploy Account and Deploy Region cannot be Empty. Please provide the values in app.<ENV>.properties"
            )

        # If all CDK Custom values are provided, set the CDK Environment and DefaultSynthesizer with the custom vales
        # provided.
        else:
            Utility.cdk_custom_configs = cdk_custom_configs

            aws_environment = cdk.Environment(
                account=cdk_custom_configs.get('stack_deploy_account'),
                region=cdk_custom_configs.get('stack_deploy_region'))

            # Set the custom bootstrap values from the application.<ENV>.properties to the stack, if its not provided
            # will use CDK default values
            cdk_synthesizer = cdk.DefaultStackSynthesizer(
                qualifier=cdk_custom_configs.get('bootstrap_qualifier', ''),
                cloud_formation_execution_role=cdk_custom_configs.get(
                    'bootstrap_cloudformation_role_arn'),
                deploy_role_arn=cdk_custom_configs.get(
                    'bootstrap_deploy_role_arn'),
                file_asset_publishing_role_arn=cdk_custom_configs.get(
                    'bootstrap_file_asset_publishing_role_arn'),
                image_asset_publishing_role_arn=cdk_custom_configs.get(
                    'bootstrap_image_assets_repository_name'),
                lookup_role_arn=cdk_custom_configs.get(
                    'bootstrap_lookup_role_arn'),
                file_assets_bucket_name=cdk_custom_configs.get(
                    'bootstrap_file_assets_bucket_name'),
                image_assets_repository_name=cdk_custom_configs.get(
                    'bootstrap_image_assets_repository_name'),
                bootstrap_stack_version_ssm_parameter=cdk_custom_configs.get(
                    'bootstrap_cdk_version_ssm_param_path',
                    '/swift/cdk-bootstrap/version'))
            return aws_environment, cdk_synthesizer
