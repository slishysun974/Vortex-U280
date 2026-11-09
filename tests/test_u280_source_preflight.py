from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_u280_source_preflight import ports, connectivity_ports


class U280ConnectivityTests(unittest.TestCase):
    def test_unconnected_masters_are_detected(self):
        top = "module vortex_afu (output m_axi_mem_0_awvalid, output m_axi_mem_31_awvalid); endmodule"
        plan = "v++ --connectivity.sp vortex_afu_1.m_axi_mem_0:HBM[0:31]"
        self.assertEqual(set(ports(top)) - set(connectivity_ports(plan)), {"31"})

    def test_instance_mentions_do_not_count_as_top_ports(self):
        top = "module vortex_afu (output m_axi_mem_0_awvalid); child c(.m_axi_mem_1_awvalid(x)); endmodule"
        self.assertEqual(ports(top), ["0"])

    def test_unrelated_kernel_connections_do_not_mask_missing_connection(self):
        plan = "vortex_afu_1.m_axi_mem_0:HBM[0:31] other_1.m_axi_mem_1:HBM[1] vortex_afu_1.m_axi_host:HOST[0]"
        self.assertEqual(connectivity_ports(plan), ["0"])


if __name__ == "__main__":
    unittest.main()
