# Compilation automatique du `.exe` sur GitHub Actions

`ci/build-exe.yml` est un modèle de workflow : il compile `TraderDesk.exe` sur
`windows-latest` à chaque push et dépose le binaire en artefact
`TraderDesk-Windows-x64` (et en release si vous poussez un tag).

## Pourquoi n'est-il pas déjà dans `.github/workflows/` ?

Le token GitHub de cette session (GitHub App) n'a **pas la permission
`workflows`** : GitHub refuse alors tout push qui ajoute ou modifie un fichier
dans `.github/workflows/` (« refusing to allow a GitHub App to create or update
workflow … without `workflows` permission »). Le fichier est donc fourni ici,
prêt à copier, sans être poussé par l'agent.

## Activer le CI en 10 secondes

Depuis un PC où votre connexion GitHub a la permission `workflows` (ou depuis
l'interface web de GitHub) :

```bat
:: Windows
mkdir .github\workflows 2>nul
copy /Y ci\build-exe.yml .github\workflows\build-exe.yml
git add .github\workflows\build-exe.yml && git commit -m "CI: build TraderDesk.exe" && git push
```

```bash
# Linux / macOS
mkdir -p .github/workflows && cp ci/build-exe.yml .github/workflows/
git add .github/workflows/build-exe.yml && git commit -m "CI: build TraderDesk.exe" && git push
```

Puis : onglet **Actions** → *Build TraderDesk.exe (Windows)* → télécharger
l'artefact. Ou poussez un tag `v1.0.0` pour obtenir une Release avec le `.exe`.

## Sans CI

Il suffit de double-cliquer sur `build_windows.bat` sur un PC Windows avec
Python 3.10+ : PyInstaller est installé automatiquement et produit
`dist\TraderDesk.exe` (autonome, sans Python requis sur la machine cible).

`release/TraderDesk-Launcher.exe` est un petit lanceur Windows natif fourni
d'emblée : il ouvre l'application au double-clic, mais il suppose Python 3
installé sur le PC (c'est le `.exe` de démarrage rapide, pas le bundle autonome).
