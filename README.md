## File watcher and notifier for GNU/Linux

#### filewatcher watches file(s) and sends mail and/or logs to syslog when the changed portion of the file(s) matches the given Regex pattern. Suitable for running via Cron.

---

##### Required packages:

- `inotify-tools`  
- `coreutils`

For Debian/derivatives `inotify-tools` can be installed by:

    apt-get install inotify-tools

GNU `coreutils` should be present on any GNU system e.g. for Debian/derivatives
the package is named `coreutils`.

Note that, these packages may be named differently on your distro; please check
out the distro packaging documentation.

---

##### Installation/Run:

- Clone the repository (`git clone git@github.com:heemayl/filewatcher.git`) or download the repository
- Run `filewatcher.py` (see `./filewatcher.py --help`)

---

