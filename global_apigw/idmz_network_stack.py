import aws_cdk as core
from aws_cdk import (
    aws_ec2 as ec2, )
from aws_cdk.aws_ec2 import IpAddresses
from constructs import Construct
from aws_cdk import Tags
from cdk_nag import NagSuppressions
from utils.utils import Utility


class IDMZNetworkStack(core.Stack):

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # Load the custom config object
        self._cdk_custom_configs = Utility.cdk_custom_configs
        self.vpc = self._create_vpc()
        # Configure NACL
        self._configure_nacl(self.vpc)

        # Incident Response SG
        sg_ir = self._create_security_group("sg-ir", self.vpc)
        # VPCE SG Definition (rules defined later)
        self.sg_vpce = self._create_security_group("sg-vpce", self.vpc)

        # NLB SG Definition (rules defined later)
        self.sg_nlb = self._create_security_group("sg-nlb", self.vpc)

        # VPCLink SG Definition (rules defined later)
        self.sg_vpclink = self._create_security_group("idmz-sg-vpcelink",
                                                      self.vpc)

        # NLB SG rules: Add Egress to VPCE from NLB and VPCLink SG
        self.sg_nlb.connections.allow_to(self.sg_vpce, ec2.Port.tcp(443),
                                         "NLB outbound to VPCE")
        # NLB SG rules: Add Egress to NLB from VPCLink SG
        self.sg_vpclink.connections.allow_to(self.sg_nlb, ec2.Port.tcp(443),
                                             "API Link outbound to NLB")

    def _create_vpc(self) -> ec2.Vpc:

        idmz_vpc = ec2.Vpc(
            self,
            "idmz-vpc",
            max_azs=int(self._cdk_custom_configs['max_azs']),
            ip_addresses=IpAddresses.cidr(
                self._cdk_custom_configs['vpc_cidr_block']),
            enable_dns_hostnames=True,
            enable_dns_support=True,
            nat_gateways=0,
            create_internet_gateway=False,
            # This attribute must be set in CDK version 2.96. Otherwise It tries to delete Default security group twice and pipeline fails.
            # https://github.com/aws/aws-cdk/issues/26390
            restrict_default_security_group=False,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    name="idmz-subnet-vpce1",
                    cidr_mask=int(self._cdk_custom_configs['vpce1_cidr_mask']),
                ),
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    name="idmz-subnet-nlb",
                    cidr_mask=int(self._cdk_custom_configs['nlb_cidr_mask']),
                ),
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    name="idmz-subnet-vpclink",
                    cidr_mask=int(
                        self._cdk_custom_configs['vpc_link_cide_mask']),
                ),
            ],
        )

        # Add the following Tags to configure VPC-Flow log. Addon will configure VPC-Flow log based on these tags.
        Tags.of(idmz_vpc).add(
            key="Name",
            value=
            f"sw-{self._cdk_custom_configs['workload']}-{self._cdk_custom_configs['appenvironment']}-vpc-{self._cdk_custom_configs['vpc_instance']}-{self._cdk_custom_configs['idmzregion']}-{self._cdk_custom_configs['lzenv']}-aws"
        )
        Tags.of(idmz_vpc).add(key="sw:application",
                              value=f"{self._cdk_custom_configs['workload']}")
        Tags.of(idmz_vpc).add(key="swift:flow-log-to-cloudwatch",
                              value="enable")
        Tags.of(idmz_vpc).add(key="swift:flow-log-to-s3", value="enable")
        Tags.of(idmz_vpc).add(key="swift:cw-flow-log-traffic-type",
                              value="reject")

        # Suppress cdk_nag finding on VPC Flow Logs
        NagSuppressions.add_resource_suppressions(
            idmz_vpc,
            [{
                'id': 'AwsSolutions-VPC7',
                'reason': 'VPCs are tagged and LZ Addon creates Flow Logs'
            }])

        return idmz_vpc

    def _configure_nacl(self, vpc: ec2.Vpc):

        #
        # Manage VPC Default NACL
        #
        # deny port 22 for Security Hub finding EC2.21 Network ACLs should not allow ingress from 0.0.0.0/0 to port 22 or port 3389
        ec2.CfnNetworkAclEntry(
            self,
            "idmz-vpcdefaultnacl-deny22",
            network_acl_id=vpc.vpc_default_network_acl,
            protocol=6,  # 6 is TCP
            rule_action="deny",
            rule_number=98,
            cidr_block="0.0.0.0/0",
            egress=False,
            port_range=ec2.CfnNetworkAclEntry.PortRangeProperty(from_=22,
                                                                to=22))
        # deny port 3389 for Security Hub finding EC2.21 Network ACLs should not allow ingress from 0.0.0.0/0 to port 22 or port 3389
        ec2.CfnNetworkAclEntry(
            self,
            "idmz-vpcdefaultnacl-deny3389",
            network_acl_id=vpc.vpc_default_network_acl,
            protocol=6,  # 6 is TCP
            rule_action="deny",
            rule_number=99,
            cidr_block="0.0.0.0/0",
            egress=False,
            port_range=ec2.CfnNetworkAclEntry.PortRangeProperty(from_=3389,
                                                                to=3389))

    def _create_security_group(self, sg_resource_name: str,
                               vpc: ec2.Vpc) -> ec2.SecurityGroup:

        # Security Groups
        security_group = ec2.SecurityGroup(
            self,
            sg_resource_name,
            vpc=vpc,
            allow_all_ipv6_outbound=False,
            allow_all_outbound=False,
            description=f"Security group for {sg_resource_name}",
            disable_inline_rules=False,
            security_group_name=
            f"sw-{self._cdk_custom_configs['workload']}-{self._cdk_custom_configs['appenvironment']}-{sg_resource_name}-{self._cdk_custom_configs['vpc_instance']}-{self._cdk_custom_configs['idmzregion']}-{self._cdk_custom_configs['lzenv']}-aws",
        )
        # For compliance rule - EC2.13: Security Groups Should Not Allow Ingress from 0.0.0.0/0 to Port 22
        security_group.add_ingress_rule(ec2.Peer.ipv4(vpc.vpc_cidr_block),
                                        ec2.Port.tcp(22))

        Tags.of(security_group).add(
            "Name",
            f"sw-{self._cdk_custom_configs['workload']}-{self._cdk_custom_configs['appenvironment']}-{sg_resource_name}-{self._cdk_custom_configs['vpc_instance']}-{self._cdk_custom_configs['idmzregion']}-{self._cdk_custom_configs['lzenv']}-aws"
        )
        Tags.of(security_group).add("sw:application",
                                    f"{self._cdk_custom_configs['workload']}")

        return security_group
