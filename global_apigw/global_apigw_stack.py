import json
import aws_cdk as core
import aws_cdk.aws_apigatewayv2 as apigwv2
import aws_cdk.aws_route53 as r53
import aws_cdk.aws_route53_targets as r53_targets
import aws_cdk.aws_s3_assets as s3assets
import aws_cdk.aws_ssm as ssm
import aws_cdk.aws_logs as logs
from constructs import Construct
from aws_cdk import Tags
from aws_cdk import CfnTag
from utils.utils import Utility
from apigw_vpce_helpers import vpce_helpers, helpers
from aws_cdk import (
    aws_apigatewayv2 as http_api,
    aws_ec2 as ec2,
    aws_certificatemanager as acm,
    aws_apigatewayv2_integrations as apigwv2_integrations,
    aws_apigatewayv2_authorizers as apigwv2_authorizers,
)


class GlobalAPIGWStack(core.Stack):

    def __init__(self, scope: Construct, id: str, vpc: ec2.Vpc,
                 sg_vpclink: ec2.SecurityGroup, sg_vpce: ec2.SecurityGroup,
                 sg_nlb: ec2.SecurityGroup, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # Load the custom config object
        self.cdk_custom_configs = Utility.cdk_custom_configs

        self.workload = self.cdk_custom_configs['workload']
        self.appenvironment = self.cdk_custom_configs['appenvironment']
        self.vpc_instance = self.cdk_custom_configs['vpc_instance']
        self.idmzregion = self.cdk_custom_configs['idmzregion']
        self.lzenv = self.cdk_custom_configs['lzenv']
        self.vpce_service_tls_fqdn = self.cdk_custom_configs[
            'vpce_service_tls_fqdn']

        apidomain = self._create_custom_domain()
        vpc_link = self._create_vpc_link(vpc, sg_vpclink)
        authorizer, listener = vpce_helpers.setup_vpce_integration(
            self,
            name="idmz-svc",
            vpc=vpc,
            vpc_link=vpc_link,
            sg_vpce=sg_vpce,
            sg_nlb=sg_nlb)

        # NLB Integration
        nlb_integration = apigwv2_integrations.HttpNlbIntegration(
            f'{self.vpc_instance}-http-nlb-integration',
            listener=listener,
            method=apigwv2.HttpMethod.ANY,
            secure_server_name=self.vpce_service_tls_fqdn,
            vpc_link=vpc_link,
        )

        # Create HTTP Api  Gateway resource
        _http_api = self._create_apigw_http_api(apidomain, authorizer,
                                                nlb_integration)

        # Create the private HTTP API
        http_route = vpce_helpers.add_http_api_routes(
            self, "idmz-svc", _http_api, listener, vpc_link,
            json.loads(self.cdk_custom_configs['routes']), authorizer,
            nlb_integration, self.vpce_service_tls_fqdn)

    def _create_custom_domain(self):
        #
        # ACM Cert used for API Custom Domain
        #

        ingress_external_fqdn = self.cdk_custom_configs[
                                    "ingress_name"] + "." + self.cdk_custom_configs[
                                    "idmz_external_zone_name"]
        idmz_external_zone_id = self.cdk_custom_configs[
            "idmz_external_zone_id"]

        l1acmcert = acm.CfnCertificate(
            self,
            "idmz-acmcert",
            domain_name=ingress_external_fqdn,
            certificate_transparency_logging_preference="DISABLED",
            validation_method="DNS",
            domain_validation_options=[
                acm.CfnCertificate.DomainValidationOptionProperty(
                    domain_name=ingress_external_fqdn,
                    hosted_zone_id=idmz_external_zone_id,
                )
            ],
            tags=[
                CfnTag(key="sw:application",
                       value=self.cdk_custom_configs["workload"]),
            ])
        # Generate L2 Certificate construct
        acmcert = acm.Certificate.from_certificate_arn(
            self, "idmz-l2acmcert", certificate_arn=l1acmcert.ref)

        #
        #upload PEM Certs to S3 for MTLS
        #
        sandboxcertasset = s3assets.Asset(
            self,
            "sandboxcert",
            path="./certs/sandbox-cert.pem",  #relative to git repository root
            deploy_time=False,
        )
        sandboxtestcertasset = s3assets.Asset(
            self,
            "sandboxtestcert",
            path=
            "./certs/sandboxtest-cert.pem",  #relative to git repository root
            deploy_time=False,
        )

        sandboxtestcertasset = s3assets.Asset(
            self,
            "sandboxqacert",
            path=
            "./certs/sandboxqa.pem",  #relative to git repository root
            deploy_time=False,
        )

        sandboxtestcertasset = s3assets.Asset(
            self,
            "sandboxdevcert",
            path=
            "./certs/sandboxdev.pem",  #relative to git repository root
            deploy_time=False,
        )
        #
        # API Gateway Custom Domain
        #
        apidomain = http_api.DomainName(
            self,
            "idmz-apicustomdomain",
            domain_name=ingress_external_fqdn,
            mtls=http_api.MTLSConfig(
                bucket=sandboxtestcertasset.bucket,
                key=sandboxtestcertasset.s3_object_key,
            ),
            certificate=acmcert,
            endpoint_type=http_api.EndpointType.REGIONAL,
            security_policy=http_api.SecurityPolicy.TLS_1_2)

        Tags.of(apidomain).add("sw:application",
                               self.cdk_custom_configs["workload"])

        # Create HostedZone object. Passing public_zone obejct does not work
        hostedzone = r53.HostedZone.from_hosted_zone_attributes(
            self,
            "idmz-hostedzone",
            hosted_zone_id=idmz_external_zone_id,
            zone_name=self.cdk_custom_configs['idmz_external_zone_name'])

        # Add DNS record pointing to API Gateway Custom Domain
        r53.ARecord(
            self,
            f"r53record-{self.cdk_custom_configs['ingress_name']}",
            target=r53.RecordTarget.from_alias(
                r53_targets.ApiGatewayv2DomainProperties(
                    regional_domain_name=apidomain.regional_domain_name,
                    regional_hosted_zone_id=apidomain.regional_hosted_zone_id)
            ),
            zone=hostedzone,
            comment="API Gateway Custom Domain",
            delete_existing=False,
            record_name=self.cdk_custom_configs['ingress_name'],
            ttl=core.Duration.seconds(60),
        )

        return apidomain

    def _create_apigw_http_api(
            self, apidomain, authorizer: apigwv2_authorizers.HttpLambdaAuthorizer, integration: apigwv2_integrations.HttpNlbIntegration):

        apigw_http_api = http_api.HttpApi(
            self,
            f"proxy-{self.cdk_custom_configs['ingress_name']}",
            create_default_stage=True,
            default_authorizer=authorizer,
            default_domain_mapping=http_api.DomainMappingOptions(
                domain_name=apidomain,
                # mapping_key = ,
            ),
            default_integration=integration,
            description=
            f"Proxy to {self.cdk_custom_configs['ingress_name']} service",
            disable_execute_api_endpoint=True)

        core.CfnOutput(self, "HttpApiEndpoint", value=apigw_http_api.url)

        # Create api-gw log group
        self._create_apigw_log_group(apigw_http_api)

        return apigw_http_api

    def _create_apigw_log_group(self, http_api):
        #
        # Logging for API Gateway
        #
        # Log Group for API GW Logs
        apilogs = logs.LogGroup(
            self,
            "idmz-api-loggroup",
            # data_protection_policy =
            # encryption_key = #default is to use AWS Managed Key
            log_group_name=
            f"/sw/apigw/proxy-{self.cdk_custom_configs['ingress_name']}",
            removal_policy=core.RemovalPolicy.DESTROY,
            retention=logs.RetentionDays.TWO_WEEKS,
        )
        Tags.of(apilogs).add("sw:application",
                             f"{self.cdk_custom_configs['workload']}")
        # JSON Log Format
        # https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-logging-variables.html
        logformat = {
            'requestId': '$context.requestId',
            'ip': '$context.identity.sourceIp',
            'requestTime': '$context.requestTime',
            'httpMethod': '$context.httpMethod',
            'path': '$context.path',
            'routeKey': '$context.routeKey',
            'status': '$context.status',
            'protocol': '$context.protocol',
            'responseLength': '$context.responseLength',
            'authorizerError': '$context.authorizer.error',
            'apigwError': '$context.error.message',
            'clientcert.subjectDN': '$context.identity.clientCert.subjectDN',
            'clientcert.issuerDN': '$context.identity.clientCert.issuerDN',
            'clientcert.serialNumber':
                '$context.identity.clientCert.serialNumber',
            'integrationError': '$context.integration.error',
            'integrationStatus': '$context.integration.status',
            'integrationErrorMessage': '$context.integrationErrorMessage'
        }
        # update access log settings on default stage via L1 construct since there is no method for it in L2
        http_api.default_stage.node.default_child.access_log_settings = apigwv2.CfnStage.AccessLogSettingsProperty(
            destination_arn=apilogs.log_group_arn,
            format=json.dumps(logformat),
        )

    def _create_vpc_link(self, vpc, sg_vpclink):

        #
        # API Gateway VPC Link (for HTTP APIs)
        #
        vpclink = http_api.VpcLink(
            self,
            'idmz-httpapi-vpclink',
            vpc=vpc,
            security_groups=[sg_vpclink],
            subnets=ec2.SubnetSelection(
                subnet_group_name="idmz-subnet-vpclink"))
        Tags.of(vpclink).add("sw:application",
                             f"{self.cdk_custom_configs['workload']}")

        return vpclink
