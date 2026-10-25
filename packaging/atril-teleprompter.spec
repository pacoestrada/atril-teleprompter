Name:           atril-teleprompter
Version:        1.0.0
Release:        1
Summary:        Offline desktop teleprompter by Paco Estrada
License:        GPL-3.0-or-later
URL:            https://github.com/pacoestrada/atril-teleprompter
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3 >= 3.10
Requires:       python3-qt5 >= 5.15

%global __brp_python_bytecompile %{nil}

%description
Atril Teleprompter is an offline desktop application for reading scripts.
It includes smooth scrolling, keyboard and mouse controls, fullscreen,
mirroring, document import and session recovery. Paco Estrada / Compilando.

%prep
%setup -q

%build
# Pure Python application; no compilation step is required.

%install
install -d %{buildroot}%{_datadir}/%{name}/assets
install -m 0644 atril.py core.py %{buildroot}%{_datadir}/%{name}/
install -m 0644 assets/atril.png assets/compilando-podcast-logo.jpg %{buildroot}%{_datadir}/%{name}/assets/
install -d %{buildroot}%{_bindir}
printf '#!/bin/sh\nexec /usr/bin/python3 /usr/share/atril-teleprompter/atril.py "$@"\n' > %{buildroot}%{_bindir}/%{name}
chmod 0755 %{buildroot}%{_bindir}/%{name}
install -Dm 0644 packaging/es.compilando.AtrilTeleprompter.desktop %{buildroot}%{_datadir}/applications/es.compilando.AtrilTeleprompter.desktop
install -Dm 0644 assets/atril.png %{buildroot}%{_datadir}/pixmaps/es.compilando.AtrilTeleprompter.png

%files
%license LICENSE
%doc README.md THIRD_PARTY.md CHANGELOG.md
%{_bindir}/%{name}
%{_datadir}/%{name}/
%{_datadir}/applications/es.compilando.AtrilTeleprompter.desktop
%{_datadir}/pixmaps/es.compilando.AtrilTeleprompter.png

%changelog
* Sun Oct 25 2026 Paco Estrada - 1.0.0-1
- First release of Atril Teleprompter.
