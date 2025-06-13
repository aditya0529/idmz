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

        # Uncomment the original VPC creation and NACL configuration calls
        self.vpc = self._create_vpc()
        self._configure_nacl()
        # Print statement to confirm we're creating a new VPC
        print(f"Creating new VPC with CIDR {self._cdk_custom_configs['vpc_cidr_block']} and configuring NACL.")

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
        
        # Check if vpc_id is missing or is a common placeholder string
        if not vpc_id or vpc_id.strip() == '' or vpc_id == 'YOUR_VPC_ID_HERE_PLEASE_UPDATE':
            raise ValueError(
                "Configuration error: 'existing_vpc_id' is not set, is empty, or is a placeholder in the properties file. "
                f"Please provide a valid VPC ID for region {self.region}."
            )

        print(f"Attempting to import existing VPC with ID: '{vpc_id}' for region {self.region}")
        
        try:
            # Using from_lookup. This requires the VPC to have been previously synthesized by CDK in the target account/region
            # or for the `cdk.context.json` to be populated with its details.
            imported_vpc = ec2.Vpc.from_lookup(self, "ImportedVpc",
                                               vpc_id=vpc_id
                                               # Other parameters like is_default=False, tags, or specific subnet configurations
                                               # can be added here if CDK cannot uniquely identify the VPC or its subnets.
                                               )
            
            # Vpc.from_lookup will raise an error if the VPC cannot be found or context is missing,
            # so an explicit check like 'if not imported_vpc.vpc_id:' is often redundant but can be a safeguard.
            if not imported_vpc or not imported_vpc.vpc_id: # Defensive check
                 raise RuntimeError(f"Vpc.from_lookup did not return a valid VPC object for ID '{vpc_id}' in region {self.region}.")

        except Exception as e:
            print(f"Error during VPC lookup for ID '{vpc_id}' in region {self.region}: {str(e)}")
            print("Please ensure the VPC exists, is accessible by the current AWS credentials, and try running 'cdk context --clear && cdk synth' to refresh context.")
            raise
        
        return imported_vpc

    def _create_vpc(self) -> ec2.Vpc:

        az_ids = self._cdk_custom_configs['az_ids'].split(',')
        az_names = self._cdk_custom_configs['azs'].split(',')

        # The original VPC had 3 subnet types. We need specific CIDRs for each.
        vpce_subnet_cidrs = self._cdk_custom_configs['vpce1_subnet_cidrs'].split(',')
        nlb_subnet_cidrs = self._cdk_custom_configs['nlb_subnet_cidrs'].split(',')
        vpclink_subnet_cidrs = self._cdk_custom_configs['vpclink_subnet_cidrs'].split(',')

        # Basic validation to ensure config lists are aligned
        num_azs = len(az_ids)
        if not (len(az_names) == num_azs and len(vpce_subnet_cidrs) == num_azs and
                len(nlb_subnet_cidrs) == num_azs and len(vpclink_subnet_cidrs) == num_azs):
            raise ValueError("Configuration error: The number of items in az_ids, azs, and all subnet CIDR lists must be identical.")

        # 2. Create the L1 CfnVPC resource
        cfn_vpc = ec2.CfnVPC(
            self,
            "idmz-vpc-cfn",
            cidr_block=self._cdk_custom_configs['vpc_cidr_block'],
            instance_tenancy="default",
            enable_dns_hostnames=True,
            enable_dns_support=True,
        )

        # Apply original tagging logic to the L1 CfnVPC resource for the LZ Addon
        Tags.of(cfn_vpc).add(
            key="Name",
            value=
            f"sw-{self._cdk_custom_configs['workload']}-{self._cdk_custom_configs['appenvironment']}-vpc-{self._cdk_custom_configs['vpc_instance']}-{self._cdk_custom_configs['idmzregion']}-{self._cdk_custom_configs['lzenv']}-aws"
        )
        Tags.of(cfn_vpc).add("sw:application", self._cdk_custom_configs["workload"])
        Tags.of(cfn_vpc).add("swift:flow-log-to-cloudwatch", "enable")
        Tags.of(cfn_vpc).add("swift:flow-log-to-s3", "enable")
        Tags.of(cfn_vpc).add("swift:cw-flow-log-traffic-type", "reject")

        # Apply Nag suppression directly to the L1 CfnVPC resource
        NagSuppressions.add_resource_suppressions(
            cfn_vpc,
            [{
                'id': 'AwsSolutions-VPC7',
                'reason': 'VPCs are tagged and LZ Addon creates Flow Logs'
            }])

        # Store the Default NACL ID from the L1 construct to be used later
        self.default_nacl_id = cfn_vpc.attr_default_network_acl

        # And convert them to L2 ISubnet objects to be passed to other stacks
        self.vpce_subnets, self.nlb_subnets, self.vpclink_subnets = [], [], []
        az_route_table_ids = [] # Store route table IDs for each AZ

        for i in range(num_azs):
            az_id = az_ids[i]
            az_name = az_names[i]

            # Create a dedicated Route Table for each AZ to match original L2 behavior
            route_table = ec2.CfnRouteTable(
                self, f"idmz-rtb-{i+1}",
                vpc_id=cfn_vpc.attr_vpc_id,
                tags=[core.CfnTag(key="Name", value=f"idmz-rtb-{az_name}")]
            )
            az_route_table_ids.append(route_table.ref)

            # VPCE Subnet
            vpce_subnet_cfn = ec2.CfnSubnet(
                self, f"idmz-subnet-vpce1-{i+1}",
                vpc_id=cfn_vpc.attr_vpc_id,
                availability_zone_id=az_id,
                cidr_block=vpce_subnet_cidrs[i],
                tags=[core.CfnTag(key="Name", value=f"idmz-subnet-vpce1-{az_name}")]
            )
            ec2.CfnSubnetRouteTableAssociation(
                self, f"vpce-rta-{i+1}",
                subnet_id=vpce_subnet_cfn.attr_subnet_id,
                route_table_id=route_table.ref
            )
            self.vpce_subnets.append(ec2.Subnet.from_subnet_attributes(self, f"vpce-subnet-l2-{i}", subnet_id=vpce_subnet_cfn.attr_subnet_id, availability_zone=az_name, route_table_id=route_table.ref))

            # NLB Subnet
            nlb_subnet_cfn = ec2.CfnSubnet(
                self, f"idmz-subnet-nlb-{i+1}",
                vpc_id=cfn_vpc.attr_vpc_id,
                availability_zone_id=az_id,
                cidr_block=nlb_subnet_cidrs[i],
                tags=[core.CfnTag(key="Name", value=f"idmz-subnet-nlb-{az_name}")]
            )
            ec2.CfnSubnetRouteTableAssociation(
                self, f"nlb-rta-{i+1}",
                subnet_id=nlb_subnet_cfn.attr_subnet_id,
                route_table_id=route_table.ref
            )
            self.nlb_subnets.append(ec2.Subnet.from_subnet_attributes(self, f"nlb-subnet-l2-{i}", subnet_id=nlb_subnet_cfn.attr_subnet_id, availability_zone=az_name, route_table_id=route_table.ref))

            # VPCLink Subnet
            vpclink_subnet_cfn = ec2.CfnSubnet(
                self, f"idmz-subnet-vpclink-{i+1}",
                vpc_id=cfn_vpc.attr_vpc_id,
                availability_zone_id=az_id,
                cidr_block=vpclink_subnet_cidrs[i],
                tags=[core.CfnTag(key="Name", value=f"idmz-subnet-vpclink-{az_name}")]
            )
            ec2.CfnSubnetRouteTableAssociation(
                self, f"vpclink-rta-{i+1}",
                subnet_id=vpclink_subnet_cfn.attr_subnet_id,
                route_table_id=route_table.ref
            )
            self.vpclink_subnets.append(ec2.Subnet.from_subnet_attributes(self, f"vpclink-subnet-l2-{i}", subnet_id=vpclink_subnet_cfn.attr_subnet_id, availability_zone=az_name, route_table_id=route_table.ref))

        # Since the original VPC had no IGW or NATs, all subnets are effectively isolated.
        # Construct the lists for Vpc.from_vpc_attributes in the correct order.
        all_isolated_subnet_ids = []
        all_isolated_subnet_route_table_ids = []

        for subnet_list_type in [self.vpce_subnets, self.nlb_subnets, self.vpclink_subnets]:
            for az_idx, subnet_in_az in enumerate(subnet_list_type):
                all_isolated_subnet_ids.append(subnet_in_az.subnet_id)
                all_isolated_subnet_route_table_ids.append(az_route_table_ids[az_idx])

        # 4. Reconstruct an L2 Vpc object from the L1 resources
        idmz_vpc = ec2.Vpc.from_vpc_attributes(
            self, "idmz-vpc",
            vpc_id=cfn_vpc.attr_vpc_id,
            availability_zones=az_names[:num_azs],
            vpc_cidr_block=cfn_vpc.cidr_block,
            isolated_subnet_ids=all_isolated_subnet_ids,
            isolated_subnet_route_table_ids=all_isolated_subnet_route_table_ids,
        )

        # 5. Apply original tagging logic and Nag suppressions to the reconstructed VPC
        # Tags are now on the L1 resource, which is what matters for deployment.
        # A simple Name tag on the L2 object is fine for CDK-level identification.
        Tags.of(idmz_vpc).add("Name", f"idmz-vpc-{self.region}")

        return idmz_vpc

    def _configure_nacl(self):

        #
        # Manage VPC Default NACL
        #
        # deny port 22 for Security Hub finding EC2.21 Network ACLs should not allow ingress from 0.0.0.0/0 to port 22 or port 3389
        deny22_entry = ec2.CfnNetworkAclEntry(
            self,
            "idmz-vpcdefaultnacl-deny22",
            network_acl_id=self.default_nacl_id,  # Use the captured default NACL ID
            protocol=6,  # 6 is TCP
            rule_action="deny",
            rule_number=98,
            cidr_block="0.0.0.0/0",
            egress=False,
            port_range=ec2.CfnNetworkAclEntry.PortRangeProperty(from_=22, to=22)
        )
        # deny port 3389 for Security Hub finding EC2.21 Network ACLs should not allow ingress from 0.0.0.0/0 to port 22 or port 3389
        deny3389_entry = ec2.CfnNetworkAclEntry(
            self,
            "idmz-vpcdefaultnacl-deny3389",
            network_acl_id=self.default_nacl_id,  # Use the captured default NACL ID
            protocol=6,  # 6 is TCP
            rule_action="deny",
            rule_number=99,
            cidr_block="0.0.0.0/0",
            egress=False,
            port_range=ec2.CfnNetworkAclEntry.PortRangeProperty(from_=3389, to=3389)
        )

        NagSuppressions.add_resource_suppressions(
            [deny22_entry, deny3389_entry],
            [
                {
                    'id': 'AwsSolutions-VPC3',
                    'reason': 'Default NACL is intentionally modified to deny specific ports (22, 3389) as per security requirements for this VPC. This aligns with original stack behavior.'
                }
            ]
        )

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