"""
Exit locations and the words on the connection panel. The engine names exits
with ISO country codes and can add one this client has never heard of, which
must still be selectable.
"""

import unittest

from nextvpn.core.regions import TUNNEL_PROTOCOLS, Regions
from nextvpn.core.status import StatusPresenter, TunnelState


class RegionsTests(unittest.TestCase):
    def test_known_codes_get_a_country_name(self):
        for code, expected in [("DE", "Germany"), ("de", "Germany"), ("GB", "United Kingdom"),
                               ("US", "United States"), ("TR", "Turkiye")]:
            self.assertEqual(expected, Regions.name_of(code))

    def test_an_unknown_code_renders_as_the_code_rather_than_as_nothing(self):
        self.assertEqual("ZZ", Regions.name_of("zz"))
        self.assertEqual("XK", Regions.name_of("XK"))

    def test_the_empty_code_is_the_let_the_engine_choose_pseudo_region(self):
        best = Regions.describe("")
        self.assertTrue(best.is_best)
        self.assertFalse(best.is_country)
        self.assertEqual("", best.code)
        self.assertEqual("Best performance", best.name)
        self.assertEqual("Best performance", best.display)

    def test_a_country_is_described_by_name_and_uppercase_code(self):
        region = Regions.describe("de")
        self.assertFalse(region.is_best)
        self.assertTrue(region.is_country)
        self.assertEqual("DE", region.code)
        self.assertEqual("Germany", region.name)
        self.assertEqual("Germany (DE)", region.display)

    def test_an_unknown_country_is_still_a_selectable_region(self):
        region = Regions.describe("zz")
        self.assertTrue(region.is_country)
        self.assertEqual("ZZ", region.code)
        self.assertEqual("ZZ (ZZ)", region.display)

    def test_codes_sort_by_the_name_a_person_reads(self):
        self.assertEqual(["AT", "DE", "GB", "US"], Regions.sorted_codes(["us", "GB", "DE", "AT", "de", ""]))

    def test_every_transport_the_settings_page_offers_has_a_name_and_a_reason(self):
        self.assertTrue(TUNNEL_PROTOCOLS)
        for p in TUNNEL_PROTOCOLS:
            self.assertTrue(p.id.strip(), p.name)
            self.assertTrue(p.name.strip(), p.id)
            self.assertTrue(p.description.strip(), p.id)
            # The engine matches LimitTunnelProtocols entries exactly.
            self.assertEqual(p.id.strip().upper(), p.id)

    def test_transport_ids_are_unique(self):
        ids = [p.id for p in TUNNEL_PROTOCOLS]
        self.assertEqual(len(ids), len(set(ids)))


class StatusPresenterTests(unittest.TestCase):
    def test_every_state_has_a_heading(self):
        for state, expected in [(TunnelState.DISCONNECTED, "Not connected"),
                                (TunnelState.CONNECTING, "Connecting"),
                                (TunnelState.CONNECTED, "Connected"),
                                (TunnelState.DISCONNECTING, "Disconnecting"),
                                (TunnelState.FAULTED, "Connection failed")]:
            self.assertEqual(expected, StatusPresenter.heading(state))

    def test_connected_subtitle_names_the_exit_country(self):
        self.assertEqual("Traffic is exiting through Germany",
                         StatusPresenter.subtitle(TunnelState.CONNECTED, "DE", None))

    def test_connected_subtitle_still_says_something_before_the_region_arrives(self):
        self.assertEqual("Your traffic is protected", StatusPresenter.subtitle(TunnelState.CONNECTED, None, None))
        self.assertEqual("Your traffic is protected", StatusPresenter.subtitle(TunnelState.CONNECTED, "", None))

    def test_fault_subtitle_prefers_the_reported_reason(self):
        self.assertEqual("Tunnel engine not found",
                         StatusPresenter.subtitle(TunnelState.FAULTED, None, "Tunnel engine not found"))

    def test_fault_subtitle_falls_back_when_nothing_was_reported(self):
        self.assertEqual("Something went wrong", StatusPresenter.subtitle(TunnelState.FAULTED, None, None))
        self.assertEqual("Something went wrong", StatusPresenter.subtitle(TunnelState.FAULTED, None, ""))

    def test_idle_subtitle_does_not_pretend_anything_is_protected(self):
        self.assertEqual("Your traffic is going out unprotected",
                         StatusPresenter.subtitle(TunnelState.DISCONNECTED, "DE", None))

    def test_action_label_says_what_the_press_will_do(self):
        for state, expected in [(TunnelState.DISCONNECTED, "Connect"), (TunnelState.FAULTED, "Connect"),
                                (TunnelState.CONNECTING, "Cancel"), (TunnelState.CONNECTED, "Disconnect"),
                                (TunnelState.DISCONNECTING, "Disconnecting")]:
            self.assertEqual(expected, StatusPresenter.action_label(state))

    def test_the_control_is_only_dead_while_the_engine_is_being_torn_down(self):
        for state in TunnelState:
            self.assertEqual(state != TunnelState.DISCONNECTING, StatusPresenter.can_toggle(state))

    def test_live_means_up_or_on_its_way_up(self):
        for state in TunnelState:
            self.assertEqual(state in (TunnelState.CONNECTED, TunnelState.CONNECTING),
                             StatusPresenter.is_live(state))


if __name__ == "__main__":
    unittest.main()
