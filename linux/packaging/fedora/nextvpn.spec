# NextVPN for Fedora. Build it from a checkout with:
#
#   linux/packaging/fedora/build-rpm.sh
#
# The bundled engine is a static, already stripped Go build that is checked
# byte for byte against its source: there is nothing in it to split into
# debuginfo, and it is installed exactly as it is.
%global debug_package %{nil}
%global __strip /bin/true
%global app_id io.github.just_elc.NextVPN

Name:           nextvpn
Version:        1.1.1
Release:        1%{?dist}
Summary:        Free internet in one click: a GTK client for the Psiphon network

# The bundled engine is GPL-3.0-only. NextVPN's own code has no licence declared
# in the repository yet; add it here ("<licence> AND GPL-3.0-only") once it does.
License:        GPL-3.0-only
URL:            https://github.com/Just-ElC/NextVPN
Source0:        NextVPN-%{version}-linux.tar.gz

# The bundled engine binary is x86_64 only. For other architectures, build it
# with linux/tools/build-engine.sh first.
ExclusiveArch:  x86_64

BuildRequires:  meson >= 0.62
BuildRequires:  gettext
BuildRequires:  python3
BuildRequires:  desktop-file-utils
BuildRequires:  appstream
BuildRequires:  gtk4-devel
BuildRequires:  glib2-devel

Requires:       python3
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       gtk4
Requires:       libadwaita >= 1.4
Requires:       gsettings-desktop-schemas
Requires:       hicolor-icon-theme
Requires:       iproute
# VPN mode, which tunnels every program. Without it only the system proxy works.
Recommends:     NetworkManager

%description
NextVPN for Linux. One button, no accounts, no subscription and no traffic
limits. Runs on the psiphon-tunnel-core engine and uses the same server network
as NextVPN for Windows. With NetworkManager every program goes through the
tunnel; without it, the GNOME and KDE system proxy is set while connected.

%prep
%autosetup -n NextVPN-%{version}

%build
%meson -Dpython3=/usr/bin/python3
%meson_build

%install
%meson_install
%find_lang %{name}

%check
%meson_test

%files -f %{name}.lang
%doc README.md
%{_bindir}/nextvpn
%{_libexecdir}/nextvpn/
%{_datadir}/nextvpn/
%{_datadir}/applications/%{app_id}.desktop
%{_datadir}/metainfo/%{app_id}.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/%{app_id}.*
%{_datadir}/icons/hicolor/scalable/status/nextvpn-tray-*.svg

%changelog
* Sun Oct 25 2026 NextOS - 1.1.1-1
- Closing the window quits the app; staying in the tray is an option
- Settings and the log show whether drawing uses the graphics card
- No status pill in the header

* Fri Oct 23 2026 NextOS - 1.1.0-1
- VPN mode: every program goes through the tunnel, through NetworkManager
- Engine built from upstream psiphon-tunnel-core of 2026-10-20
- Tray icon shows on quickshell-based shells; no upstream banners

* Sun Oct 18 2026 NextOS - 1.0.0-1
- First release for Linux
