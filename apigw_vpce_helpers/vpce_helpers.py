import json
import pathlib
import aws_cdk as core
from typing import List
from aws_cdk.aws_apigatewayv2_authorizers_alpha import HttpLambdaAuthorizer, HttpLambdaResponseType
from aws_cdk import Tags
from cdk_nag import NagSuppressions
from utils.utils import Utility
from aws_cdk import (
    aws_apigatewayv2_alpha as apigwv2_alpha,
    aws_apigatewayv2_integrations_alpha as apigwv2_integrations_alpha,
    aws_logs as logs,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_targets as elbv2_targets,
    aws_iam as iam,
    aws_lambda as lambda_,
)


def setup_vpce_integration(stack, name: str, vpc: ec2.Vpc,
                           vpc_link: apigwv2_alpha.VpcLink,
                           sg_vpce: ec2.SecurityGroup,
                           sg_nlb: ec2.SecurityGroup):
    """Create the integration between an HTTP API and VPC Endpoint Service running in another account.

    This manages several things:

    - VPC Endpoint which connects to the service's VPC Endpoint Service
    - Network Load Balancer for that VPC Endpoint, using the VPCE's private IPs
    - HTTP Api Integration to the global API Gateway HTTP API
    - creating HTTP Api routes to the endpoint service

    There is a fair amount of complexity in here, much around the custom resource which will return
    private IPs from the ENIs created in the VPC Endpoint. While it's possible to get the ENIs
    in raw CloudFormation, it's not possible to get the IPs associated with those ENIs without
    making an API call.

    See:

    https://github.com/aws-cloudformation/aws-cloudformation-coverage-roadmap/issues/109

    Note, all of this can easily be ported to a CDK stack by changing the functions to class methods
    and renaming `stack` to `self`.

    """
    # Load the custom config object
    cdk_custom_configs = Utility.cdk_custom_configs

    vpc_endpoint = _createvpc_endpoint(stack, name, vpc, sg_vpce,
                                       cdk_custom_configs)

    # The VPC Endpoint creates multiple private IP addresses across the private subnets. These are
    # needed to setup our ALB. To fetch the IPs, we need a custom CFN resource.
    vpc_endpoint_ips = _create_custom_resource(
        stack,
        name=name,
        vpce_enis=vpc_endpoint.vpc_endpoint_network_interface_ids)
    private_ips = [
        vpc_endpoint_ips.get_att_string("IP0"),
        vpc_endpoint_ips.get_att_string("IP1"),
    ]

    # Now, create the Network Target Group for the VPC Endpoint
    target_group = _create_network_target_group(stack, name, vpc, private_ips,
                                                cdk_custom_configs)

    listener = _create_nlb(stack, name, vpc, target_group, sg_nlb,
                           cdk_custom_configs)

    lambda_authorizer = _lambda_authorizer(stack, "lambda-auth")

    # For Simple authorizer
    authorizer = HttpLambdaAuthorizer(
        "idmz-httpappi-lambdaAuthorizer",
        lambda_authorizer,
        identity_source=[
            "$context.identity.sourceIp",
            "$context.identity.clientCert.clientCertPem",
        ],
        response_types=[HttpLambdaResponseType.SIMPLE])

    # For IAM based Authorizer - Uncomment this if you want to use this feature.
    # authorizer = apigwv2_alpha_authorizer.HttpLambdaAuthorizer(
    #     "Authorizer", lambda_authorizer, response_types=[apigwv2_alpha_authorizer.HttpLambdaResponseType.IAM])

    return authorizer, listener


def _createvpc_endpoint(stack, name: str, vpc: ec2.Vpc,
                        sg_vpce: ec2.SecurityGroup,
                        cdk_custom_configs: dict) -> ec2.InterfaceVpcEndpoint:
    """Create the VPC Endpoint which connects to a VPC Endpoint service.

    Note that the vpc.add_interface_endpoint method is slightly simpler to use, but has created
    circular references between child and the parent stack which owns the VPC.

    """
    endpoint_service = ec2.InterfaceVpcEndpointService(
        cdk_custom_configs['vpce_service_name'], port=443)

    # private_dns_enabled = False. For iDMZ use case, this must be False because to make requests
    # to service using IP address (ENI-VPCE Service in App account)
    interface_vpc_endpoint = vpc.add_interface_endpoint(
        f"vpce-{cdk_custom_configs['ingress_name']}-interface-endpoint",
        service=endpoint_service,
        lookup_supported_azs=False,
        open=False,
        private_dns_enabled=False,
        security_groups=[sg_vpce],
        subnets=ec2.SubnetSelection(subnet_group_name="idmz-subnet-vpce1"))

    if eval(cdk_custom_configs['interface_vpce_policy_allowed']):
        interface_vpc_endpoint.add_to_policy(
            iam.PolicyStatement.from_json({
                "Effect":
                    cdk_custom_configs['interface_vpce_policy_effect'],
                "Action":
                    cdk_custom_configs['interface_vpce_policy_action'],
                "Principal":
                    cdk_custom_configs['interface_vpce_policy_principal'],
                "Resource":
                    cdk_custom_configs['interface_vpce_policy_resource']
            }))

    return interface_vpc_endpoint


def _create_custom_resource(stack, name: str, **kwargs) -> core.CustomResource:
    parent_dir = pathlib.Path(__file__).parent
    code_dir = str(
        parent_dir.joinpath('custom_resource/get_vpc_private_ip_lambda'))
    code = lambda_.Code.from_asset(code_dir)

    custom_resource_func = lambda_.Function(
        stack,
        f"{name}-CustomResourceFunction",
        code=code,
        handler="handler.main_handler",
        timeout=core.Duration.seconds(15),
        runtime=lambda_.Runtime.PYTHON_3_11,
    )
    custom_resource_func.add_to_role_policy(
        iam.PolicyStatement(
            actions=["ec2:DescribeNetworkInterfaces"],
            effect=iam.Effect.ALLOW,
            resources=['*'],
        ))

    # Suppress cdk_nag finding for resource star
    NagSuppressions.add_resource_suppressions(custom_resource_func, [{
        "id":
            "AwsSolutions-IAM5",
        "reason":
            "Resource star for DescribeNetworkInterfaces, and see comment about use of log_retention parameter in AwsCustomResource",
    }, {
        "id":
            "AwsSolutions-IAM4",
        "reason":
            "Role policy selected by use of AwsCustomResource construct uses AWSLambdaBasicExecutionRole",
        "appliesTo": [
            "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        ]
    }],
                                              apply_to_children=True)

    return core.CustomResource(
        stack,
        f"{name}-ENIPrivateIPResource",
        resource_type=f"Custom::{name}-CustomResourceFunction",
        service_token=custom_resource_func.function_arn,
        properties=kwargs,
    )


def _create_network_target_group(
        stack, name: str, vpc: ec2.Vpc, vpc_endpoint_ips: List[str],
        cdk_custom_configs: dict) -> elbv2.NetworkTargetGroup:

    targets = [
        elbv2_targets.IpTarget(ip_address=ip) for ip in vpc_endpoint_ips
    ]

    # enabled (Optional[bool]) – Indicates whether health checks are enabled.
    # If the target type is lambda, health checks are disabled by default but can be enabled.
    # If the target type is instance or ip, health checks are always enabled and cannot be disabled.
    # Default: - Determined automatically.

    # health_check = elbv2.HealthCheck(
    #     healthy_threshold_count=3,
    #     interval=core.Duration.seconds(15),
    #     timeout=core.Duration.seconds(2),
    # )
    return elbv2.NetworkTargetGroup(
        stack,
        "idmz-nlb-targetgroup",
        # port=int(cdk_custom_configs['integration_port']),
        port=443,
        connection_termination=eval(
            cdk_custom_configs['nw_targetgroup_connection_termination']),
        preserve_client_ip=eval(cdk_custom_configs['nw_preserve_client_ip']),
        protocol=elbv2.Protocol.TCP,
        targets=targets,
        vpc=vpc,
    )


def _create_nlb(stack, name: str, vpc: ec2.Vpc,
                target_group: elbv2.NetworkTargetGroup,
                sg_nlb: ec2.SecurityGroup,
                cdk_custom_configs: dict) -> elbv2.NetworkListener:
    """Create Network Load Balancer for integration to the service's API"""

    nlb = elbv2.NetworkLoadBalancer(
        stack,
        f'idmz-nlb',
        cross_zone_enabled=False,
        deletion_protection=False,
        vpc=vpc,
        internet_facing=False,
        vpc_subnets=ec2.SubnetSelection(subnet_group_name="idmz-subnet-nlb"),
    )
    Tags.of(nlb).add(
        "Name",
        f"sw-{cdk_custom_configs['workload']}-{cdk_custom_configs['appenvironment']}-idmz-sg-nlb-{cdk_custom_configs['idmzregion']}-{cdk_custom_configs['lzenv']}-aws"
    )
    Tags.of(nlb).add("sw:application", f"{cdk_custom_configs['workload']}")

    # Add SG to NLB using Override because CDK Construct does not support it yet
    (nlb.node.default_child).add_property_override("SecurityGroups",
                                                   [sg_nlb.security_group_id])
    # Suppress cdk_nag finding on ELB Access Logs
    NagSuppressions.add_resource_suppressions(nlb, [{
        'id': 'AwsSolutions-ELB2',
        'reason': 'Access Logs TBD'
    }])

    nlb_listener = nlb.add_listener(
        'idmz-nlb-listener',
        port=int(cdk_custom_configs['integration_port']),
        default_action=elbv2.NetworkListenerAction.forward(
            target_groups=[target_group]),
        protocol=elbv2.Protocol.TCP,
    )

    return nlb_listener


def _lambda_authorizer(stack, name: str, **kwargs) -> lambda_.Function:

    parent_dir = pathlib.Path(__file__).parent
    code_dir = str(parent_dir.joinpath('custom_resource/authorizer_lambda'))
    code = lambda_.Code.from_asset(code_dir)

    authorizer_lambda = lambda_.Function(
        stack,
        "LambdaAuthorizer",
        handler='api-gateway-lambda-http-authorizer-simple.lambda_handler',
        runtime=lambda_.Runtime.PYTHON_3_11,
        log_retention=logs.RetentionDays.TWO_WEEKS,
        timeout=core.Duration.seconds(300),
        code=code)

    NagSuppressions.add_resource_suppressions(stack, [{
        "id":
            "AwsSolutions-IAM5",
        "reason":
            "Resource star for Lambd Authorizer, and see comment about use of log_retention parameter in AwsCustomResource",
        "appliesTo": ["Resource::*"]
    }, {
        "id":
            "AwsSolutions-IAM4",
        "reason":
            "Role policy selected by use of Function construct uses AWSLambdaBasicExecutionRole",
        "appliesTo": [
            "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        ]
    }],
                                              apply_to_children=True)

    return authorizer_lambda


def add_http_api_routes(stack, name: str,
                        http_api: core.aws_apigatewayv2_alpha.HttpApi,
                        listener: elbv2.NetworkListener,
                        vpc_link: apigwv2_alpha.VpcLink, routes: List[str],
                        authorizer: core.aws_apigatewayv2_authorizers_alpha.
                        HttpLambdaAuthorizer, integration: core.
                        aws_apigatewayv2_integrations_alpha.HttpNlbIntegration,
                        vpce_service_tls_fqdn: str) -> List:

    parent_dir = pathlib.Path(__file__).parent
    code_dir = str(parent_dir.joinpath('custom_resource/idmzhealth'))
    code = lambda_.Code.from_asset(code_dir)

    idmzhealth_lambda = lambda_.Function(
        stack,
        "IdmzHealthFunction",
        handler='handler.lambda_handler',
        runtime=lambda_.Runtime.PYTHON_3_11,
        log_retention=logs.RetentionDays.TWO_WEEKS,
        timeout=core.Duration.seconds(300),
        code=code)

    Tags.of(idmzhealth_lambda).add("sw:application", "idmz")

    NagSuppressions.add_resource_suppressions(idmzhealth_lambda, [{
        "id":
            "AwsSolutions-IAM4",
        "reason":
            "Role policy selected by use of Function construct uses AWSLambdaBasicExecutionRole",
        "appliesTo": [
            "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        ]
    }],
                                              apply_to_children=True)

    # Add Route for /idmzhealth pointing to the health lambda
    http_api.add_routes(
        path="/idmzhealth",
        methods=[apigwv2_alpha.HttpMethod.GET],
        authorizer=authorizer,
        integration=apigwv2_integrations_alpha.HttpLambdaIntegration(
            "idmz-httpapi-lambdaintegration-healthcheck",
            handler=idmzhealth_lambda,
            # parameter_mapping =
            payload_format_version=apigwv2_alpha.PayloadFormatVersion.
            VERSION_2_0))

    # API does not allow to create default route $default. It expects / in the path.
    route = []
    for i, route_key in enumerate(routes):
        route = apigwv2_alpha.HttpRoute(
            stack,
            f"{name}-route-{i+1}",
            http_api=http_api,
            integration=integration,
            route_key=apigwv2_alpha.HttpRouteKey.with_(
                route_key, apigwv2_alpha.HttpMethod.ANY),
            authorizer=authorizer,
        )
        integration.bind(route=route, scope=stack)

    return route
