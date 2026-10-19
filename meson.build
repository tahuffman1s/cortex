project('cortex',
  version: '0.1.0',
  meson_version: '>= 0.62.0',
  license: 'GPL-3.0-or-later',
)

app_id = 'io.github.tahuffman1s.Cortex'
python = import('python').find_installation('python3')
pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()

conf = configuration_data()
conf.set('PYTHON', python.full_path())
conf.set('pkgdatadir', pkgdatadir)
configure_file(
  input: 'cortex.in',
  output: 'cortex',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)

install_subdir('src/cortex', install_dir: pkgdatadir, exclude_directories: ['__pycache__'])

install_data('data' / app_id + '.desktop', install_dir: get_option('datadir') / 'applications')
install_data('data' / app_id + '.metainfo.xml', install_dir: get_option('datadir') / 'metainfo')
install_subdir('data/icons', install_dir: get_option('datadir'), strip_directory: false)

desktop_file_validate = find_program('desktop-file-validate', required: false)
if desktop_file_validate.found()
  test('desktop file', desktop_file_validate, args: [meson.project_source_root() / 'data' / app_id + '.desktop'])
endif
appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test('metainfo', appstreamcli,
    args: ['validate', '--no-net', '--explain', meson.project_source_root() / 'data' / app_id + '.metainfo.xml'])
endif
test('unit tests', python,
  args: ['-m', 'unittest', 'discover', '-s', meson.project_source_root() / 'tests'],
  env: ['PYTHONPATH=' + meson.project_source_root() / 'src'])

gnome = import('gnome')
gnome.post_install(gtk_update_icon_cache: true, update_desktop_database: true)
