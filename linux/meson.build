# Builds and installs NextVPN for Linux:
#
#   <prefix>/bin/nextvpn                                launcher
#   <prefix>/share/nextvpn/nextvpn/                      the application
#   <prefix>/share/nextvpn/engine/                       base.config, server_list.dat
#   <prefix>/libexec/nextvpn/psiphon-tunnel-core         the engine (-Dengine=bundled)
#   <prefix>/share/applications, metainfo, icons, locale
#
# Nothing runs as root and nothing is installed outside the prefix.

python = import('python')
i18n = import('i18n')
gnome = import('gnome')
fs = import('fs')

app_id = 'io.github.just_elc.NextVPN'
py = python.find_installation('python3')

prefix = get_option('prefix')
bindir = prefix / get_option('bindir')
datadir = prefix / get_option('datadir')
libexecdir = prefix / get_option('libexecdir')
localedir = prefix / get_option('localedir')
pkgdatadir = datadir / meson.project_name()
engine_data_dir = pkgdatadir / 'engine'

# ------------------------------------------------------------------ engine

engine = get_option('engine')
if engine == 'bundled'
  bundled = 'engine' / 'psiphon-tunnel-core-' + host_machine.cpu_family()
  if not fs.is_file(bundled)
    error('There is no bundled tunnel engine for ' + host_machine.cpu_family() + '. '
          + 'Build one with linux/tools/build-engine.sh, or configure with '
          + '-Dengine=/path/to/psiphon-tunnel-core or -Dengine=path.')
  endif
  install_data(bundled,
    install_dir: libexecdir / 'nextvpn',
    rename: 'psiphon-tunnel-core',
    install_mode: 'rwxr-xr-x',
  )
  engine_binary = libexecdir / 'nextvpn' / 'psiphon-tunnel-core'
elif engine == 'path'
  engine_binary = ''
else
  engine_binary = engine
endif

# The sponsor identity and the embedded server list: the very same files the
# Windows build ships, so both connect to the same servers.
install_data('../engine/base.config', '../engine/server_list.dat',
  install_dir: engine_data_dir,
)

# ------------------------------------------------------------- application

build_conf = configuration_data()
build_conf.set('VERSION', meson.project_version())
build_conf.set('LOCALEDIR', localedir)
build_conf.set('ENGINE_BINARY', engine_binary)
build_conf.set('ENGINE_DATA_DIR', engine_data_dir)
build_conf.set('ICONS_DIR', datadir / 'icons')
configure_file(
  input: 'nextvpn/buildconfig.py.in',
  output: 'buildconfig.py',
  configuration: build_conf,
  install_dir: pkgdatadir / 'nextvpn',
)

install_subdir('nextvpn',
  install_dir: pkgdatadir,
  exclude_files: ['buildconfig.py.in'],
  exclude_directories: ['__pycache__', 'core/__pycache__', 'ui/__pycache__'],
)

launcher_conf = configuration_data()
launcher_conf.set('PYTHON', py.full_path())
launcher_conf.set('PKGDATADIR', pkgdatadir)
launcher_conf.set('LAUNCHER', bindir / 'nextvpn')
configure_file(
  input: 'nextvpn.in',
  output: 'nextvpn',
  configuration: launcher_conf,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)

# -------------------------------------------------------------------- data

# A bare command name only works where the launcher is on every session's PATH;
# anything else, ~/.local included, gets the absolute path.
desktop_conf = configuration_data()
desktop_conf.set('EXEC', prefix in ['/usr', '/usr/local'] ? 'nextvpn' : bindir / 'nextvpn')
desktop_file = configure_file(
  input: 'data' / app_id + '.desktop.in',
  output: app_id + '.desktop',
  configuration: desktop_conf,
  install_dir: datadir / 'applications',
)
metainfo_file = files('data' / app_id + '.metainfo.xml')
install_data(metainfo_file, install_dir: datadir / 'metainfo')
install_subdir('data/icons/hicolor', install_dir: datadir / 'icons')

subdir('po')

# Refreshes the icon and desktop caches on a direct install. Packaging builds
# install into a DESTDIR, where this is skipped, and may not have the tools.
gnome.post_install(
  gtk_update_icon_cache: find_program('gtk4-update-icon-cache', 'gtk-update-icon-cache', required: false).found(),
  update_desktop_database: find_program('update-desktop-database', required: false).found(),
)

# ------------------------------------------------------------------- tests

if get_option('tests')
  test('unit tests', py,
    args: ['-m', 'unittest', 'discover', '-s', 'tests', '-t', '.'],
    workdir: meson.current_source_dir(),
    timeout: 300,
  )

  desktop_file_validate = find_program('desktop-file-validate', required: false)
  if desktop_file_validate.found()
    test('desktop file', desktop_file_validate, args: [desktop_file])
  endif

  appstreamcli = find_program('appstreamcli', required: false)
  if appstreamcli.found()
    test('metainfo', appstreamcli, args: ['validate', '--no-net', '--explain', metainfo_file])
  endif
endif
