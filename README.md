# GitLab-Status-Logger (FH Aachen)

Fragt alle 5 Minuten die Uptime-Kuma-Statusseite ab, speichert neue Messpunkte als CSV (`data/JJJJ-MM.csv`)
und veröffentlicht ein Dashboard auf GitHub Pages.

## Einrichten
1. Alle Dateien in dein Repository kopieren (Ordnerstruktur beibehalten, inkl. `.github/`).
2. Repository → Settings → Pages → Source: **GitHub Actions**.
3. Repository → Settings → Actions → General → Workflow permissions: **Read and write permissions**.
4. Actions → „Monitor“ → **Run workflow**. Danach läuft es automatisch.

## Auswertung
- Verfügbarkeit = Messpunkte mit Status Up / (Up + Down + Pending). Wartung wird nicht gewertet.
- Ist der Abstand zwischen zwei Messpunkten größer als `GAP_MIN` (5 Min.), gilt der Zeitraum als „keine Daten“.
- Tage, Wochen (ISO, Montag) und Monate richten sich nach Europe/Berlin.
