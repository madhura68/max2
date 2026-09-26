import unittest

from docker_ports import published_ports


class DockerPortsTest(unittest.TestCase):
    def test_single_published_port(self):
        out = "scrum4me-worker-idea-1\t0.0.0.0:18082->8080/tcp\n"
        self.assertEqual(published_ports(out, "scrum4me-worker"), {"scrum4me-worker-idea-1": [18082]})

    def test_ipv4_and_ipv6_counted_once(self):
        out = "w-1\t0.0.0.0:18083->8080/tcp, [::]:18083->8080/tcp\n"
        self.assertEqual(published_ports(out, "w-"), {"w-1": [18083]})

    def test_prefix_filter(self):
        out = ("scrum4me-worker-idea-1\t0.0.0.0:18082->8080/tcp\n"
               "scrum4me-caddy\t0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp\n"
               "scrum4me-worker-idea-2\t0.0.0.0:18083->8080/tcp\n")
        self.assertEqual(published_ports(out, "scrum4me-worker"),
                         {"scrum4me-worker-idea-1": [18082], "scrum4me-worker-idea-2": [18083]})

    def test_exposed_only_is_ignored(self):
        out = "tei-gpu\t8080/tcp, 100.102.8.64:8080->80/tcp\n"
        self.assertEqual(published_ports(out, "tei"), {"tei-gpu": [8080]})

    def test_range_expanded(self):
        out = "w\t0.0.0.0:18080-18082->8080-8082/tcp\n"
        self.assertEqual(published_ports(out, "w"), {"w": [18080, 18081, 18082]})

    def test_udp_included_and_sorted_unique(self):
        out = "dns\t0.0.0.0:5353->5353/udp, 127.0.0.1:53->53/tcp, 0.0.0.0:5353->5353/tcp\n"
        self.assertEqual(published_ports(out, "dns"), {"dns": [53, 5353]})

    def test_no_ports_column(self):
        out = "migrate-1\t\nmigrate-2\n"
        self.assertEqual(published_ports(out, "migrate"), {"migrate-1": [], "migrate-2": []})

    def test_blank_lines_ignored(self):
        out = "\n\nw-1\t0.0.0.0:1->1/tcp\n\n"
        self.assertEqual(published_ports(out, "w"), {"w-1": [1]})

    def test_empty_output(self):
        self.assertEqual(published_ports("", "w"), {})

    def test_ipv6_specific_address(self):
        out = "x\t[::1]:9000->9000/tcp, 192.168.0.10:9001->9000/tcp\n"
        self.assertEqual(published_ports(out, "x"), {"x": [9000, 9001]})


if __name__ == "__main__":
    unittest.main()
