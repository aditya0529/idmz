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

        # Always import the existing VPC
        self.vpc = self._import_existing_vpc()

        # Comment out VPC creation logic (no longer called directly)
        # # if should_import_vpc:
        # #     self.vpc = self._import_existing_vpc()
        # # else:
        # #     self.vpc = self._create_vpc()

        # Comment out NACL configuration logic
        # # if should_configure_nacl_for_imported_vpc or not should_import_vpc:
        # #    self._configure_nacl(self.vpc)
        # # else:
        # #    print(f"Skipping NACL configuration for imported VPC {self.vpc.vpc_id} as per settings.")
        print(f"Using imported VPC {self.vpc.vpc_id}. NACL configuration by this stack is disabled.")

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

    def _import_existing_vpc(self) -> ec2.IVpc:
        # Ensure 'existing_vpc_id' is present in the regional or cdk_settings config
        vpc_id = self._cdk_custom_configs.get('existing_vpc_id')
        if not vpc_id or vpc_id == 'YOUR_VPC_ID_HERE_PLEASE_UPDATE': # Check against common placeholder
            raise ValueError("Configuration error: 'existing_vpc_id' is not set in properties or is a placeholder.")

        print(f"Attempting to import existing VPC with ID: {vpc_id} for region {self.region}")
        
        # Using from_lookup. This requires the VPC to have been previously synthesized by CDK in the target account/region
        # or for the `cdk.context.json` to be populated with its details.
        imported_vpc = ec2.Vpc.from_lookup(self, "ImportedVpc",
                                           vpc_id=vpc_id
                                           # region=self.region # Ensure lookup is region-specific if not implicit
                                           # is_default=False # Typically false for specific VPCs
                                           )
        if not imported_vpc.vpc_id:
             raise RuntimeError(f"Failed to look up VPC with ID {vpc_id}. Ensure it exists, is accessible, and 'cdk context' might be needed.")
        
        return imported_vpc

    # _create_vpc method remains but is no longer called by __init__
    def _create_vpc(self) -> ec2.Vpc:
        print("WARNING: _create_vpc is defined but should not be called when always importing VPCs.")
        idmz_vpc = ec2.Vpc(
            self,
            "idmz-vpc-unused", # Renamed to avoid conflict if accidentally called
            max_azs=int(self._cdk_custom_configs.get('max_azs', 2)), # Provide defaults
            ip_addresses=IpAddresses.cidr(
                self._cdk_custom_configs.get('vpc_cidr_block', '10.0.0.0/16')), # Provide defaults
            enable_dns_hostnames=True,
            enable_dns_support=True,
            nat_gateways=0,
            create_internet_gateway=False,
            restrict_default_security_group=False,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    name=self._cdk_custom_configs.get('existing_vpce_subnet_name', "idmz-subnet-vpce1"),
                    cidr_mask=int(self._cdk_custom_configs.get('vpce1_cidr_mask', 24)), # Provide defaults
                ),
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    name=self._cdk_custom_configs.get('existing_nlb_subnet_name', "idmz-subnet-nlb"),
                    cidr_mask=int(self._cdk_custom_configs.get('nlb_cidr_mask', 24)), # Provide defaults
                ),
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    name=self._cdk_custom_configs.get('existing_vpclink_subnet_name', "idmz-subnet-vpclink"),
                    cidr_mask=int(
                        self._cdk_custom_configs.get('vpc_link_cidr_mask', 24)), # Corrected typo and provide default
                ),
            ],
        )
        # ... (Tagging and suppression logic remains but won't be executed if method not called)
        Tags.of(idmz_vpc).add(key="Name", value="unused-vpc") # Simplified tagging
        return idmz_vpc

    # _configure_nacl method remains but is no longer called by __init__
    def _configure_nacl(self, vpc: ec2.IVpc):
        print(f"WARNING: _configure_nacl is defined but should not be called when always importing VPCs (VPC ID: {vpc.vpc_id}).")
        # ... (NACL entry creation logic remains but won't be executed if method not called)
        ec2.CfnNetworkAclEntry(
            self,
            "idmz-vpcdefaultnacl-deny22-unused",
            network_acl_id=vpc.vpc_default_network_acl, # This would fail if vpc is IVpc and doesn't have this attr directly
            protocol=6,
            rule_action="deny",
            rule_number=98,
            cidr_block="0.0.0.0/0",
            egress=False,
            port_range=ec2.CfnNetworkAclEntry.PortRangeProperty(from_=22,
                                                                to=22))
        ec2.CfnNetworkAclEntry(
            self,
            "idmz-vpcdefaultnacl-deny3389-unused",
            network_acl_id=vpc.vpc_default_network_acl,
            protocol=6,
            rule_action="deny",
            rule_number=99,
            cidr_block="0.0.0.0/0",
            egress=False,
            port_range=ec2.CfnNetworkAclEntry.PortRangeProperty(from_=3389,
                                                                to=3389))

    def _create_security_group(self, sg_resource_name: str,
                               vpc: ec2.IVpc) -> ec2.SecurityGroup:

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
