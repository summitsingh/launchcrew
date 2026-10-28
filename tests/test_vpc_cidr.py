"""Offline VPC CIDR checks for the demo CloudFormation template.

No test contacts AWS. The template text is parsed with the standard
library only, and every network claim is proven with ipaddress arithmetic:
the demo VPC is exactly 10.42.0.0/16, all four demo subnets sit inside it,
no two demo ranges overlap, and none of them collides with the observed
generic ranges 10.0.0.0/16 and 172.31.0.0/16. No account ID, production
name, or spend figure appears here.
"""
import ipaddress
import re
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "deploy" / "aws" / "fargate.yaml"

EXPECTED_VPC = ipaddress.ip_network("10.42.0.0/16")
EXPECTED_SUBNETS = {
    "PublicSubnetA": ipaddress.ip_network("10.42.1.0/24"),
    "PublicSubnetB": ipaddress.ip_network("10.42.2.0/24"),
    "PrivateSubnetA": ipaddress.ip_network("10.42.11.0/24"),
    "PrivateSubnetB": ipaddress.ip_network("10.42.12.0/24"),
}
GENERIC_RANGES = (
    ipaddress.ip_network("10.0.0.0/16"),
    ipaddress.ip_network("172.31.0.0/16"),
)


def resource_block(text, name):
    start = text.index(f"  {name}:")
    rest = text[start:]
    lines = rest.splitlines()
    block = [lines[0]]
    for line in lines[1:]:
        if re.match(r"^  \S", line):
            break
        block.append(line)
    return "\n".join(block)


class VpcCidrTests(unittest.TestCase):
    def setUp(self):
        self.text = TEMPLATE.read_text(encoding="utf-8")

    def cidr_in(self, resource):
        match = re.search(r"CidrBlock:\s*(\S+)", resource_block(self.text, resource))
        self.assertIsNotNone(match, msg=f"{resource} has no CidrBlock")
        return ipaddress.ip_network(match.group(1))

    def test_vpc_is_exactly_demo_range(self):
        self.assertEqual(self.cidr_in("Vpc"), EXPECTED_VPC)

    def test_all_four_subnets_match_expected_ranges(self):
        for name, expected in EXPECTED_SUBNETS.items():
            with self.subTest(subnet=name):
                self.assertEqual(self.cidr_in(name), expected)

    def test_every_subnet_sits_inside_vpc(self):
        vpc = self.cidr_in("Vpc")
        for name in EXPECTED_SUBNETS:
            with self.subTest(subnet=name):
                self.assertTrue(
                    self.cidr_in(name).subnet_of(vpc),
                    msg=f"{name} is not inside {vpc}")

    def test_demo_ranges_never_overlap(self):
        ranges = [("Vpc", self.cidr_in("Vpc"))]
        ranges += [(name, self.cidr_in(name)) for name in EXPECTED_SUBNETS]
        subnets = ranges[1:]
        for index, (left_name, left) in enumerate(subnets):
            for right_name, right in subnets[index + 1:]:
                self.assertFalse(
                    left.overlaps(right),
                    msg=f"{left_name} {left} overlaps {right_name} {right}")

    def test_demo_ranges_avoid_generic_ranges(self):
        checked = [self.cidr_in("Vpc")]
        checked += [self.cidr_in(name) for name in EXPECTED_SUBNETS]
        for generic in GENERIC_RANGES:
            for candidate in checked:
                with self.subTest(candidate=str(candidate), generic=str(generic)):
                    self.assertFalse(candidate.overlaps(generic))

    def test_az_order_pairs_public_with_private(self):
        az_index = {}
        for name in EXPECTED_SUBNETS:
            block = resource_block(self.text, name)
            match = re.search(r"!Select\s*\[\s*(\d)", block)
            self.assertIsNotNone(match, msg=f"{name} has no AZ select")
            az_index[name] = int(match.group(1))
        self.assertEqual(az_index["PublicSubnetA"], 0)
        self.assertEqual(az_index["PrivateSubnetA"], 0)
        self.assertEqual(az_index["PublicSubnetB"], 1)
        self.assertEqual(az_index["PrivateSubnetB"], 1)

    def test_public_ip_policy_matches_subnet_role(self):
        for name in ("PublicSubnetA", "PublicSubnetB"):
            block = resource_block(self.text, name)
            self.assertIn("MapPublicIpOnLaunch: true", block, msg=name)
        for name in ("PrivateSubnetA", "PrivateSubnetB"):
            block = resource_block(self.text, name)
            self.assertIn("MapPublicIpOnLaunch: false", block, msg=name)

    def test_db_subnet_group_uses_private_only(self):
        start = self.text.index("DbSubnetGroup:")
        group = self.text[start:start + 800]
        self.assertIn("PrivateSubnetA", group)
        self.assertIn("PrivateSubnetB", group)
        self.assertNotIn("PublicSubnet", group)


if __name__ == "__main__":
    unittest.main()
