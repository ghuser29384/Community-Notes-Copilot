from pathlib import Path

root = Path(__file__).resolve().parents[2] / "target"

# Preserve the source repository's CRLF line endings in DeckService.
deck = root / "src/app/services/cards/deck.service.ts"
data = deck.read_bytes()
remove_block = (
    b"  containsTrainingWord(str) {\r\n"
    b"    const words = this.trainingWords;\r\n"
    b"    for (const word of words) {\r\n"
    b"      if (str.toLowerCase().includes(word.toLowerCase())) {\r\n"
    b"        return true;\r\n"
    b"      }\r\n"
    b"    }\r\n"
    b"    return false;\r\n"
    b"  }\r\n\r\n"
)
if data.count(remove_block) != 1:
    raise SystemExit("Expected exactly one containsTrainingWord block")
data = data.replace(remove_block, b"")
old = b"      is_training : this.getReportType() === 'training' || this.containsTrainingWord(this.description)\r\n"
new = b"      is_training: this.getReportType() === 'training'\r\n"
if data.count(old) != 1:
    raise SystemExit("Expected exactly one free-text training classification line")
deck.write_bytes(data.replace(old, new))

# Respect the explicit training/real choice in the giver flow.
giver = root / "src/app/routes/decks/giver/giver.component.ts"
text = giver.read_text()
old = "    this.deckService.selectReportType('real');"
new = "    this.deckService.selectReportType(type);"
if text.count(old) != 1:
    raise SystemExit("Expected exactly one hard-coded giver report type")
giver.write_text(text.replace(old, new))

# The package is already imported by Angular components; concatenating its
# CommonJS lib/index.js as a browser global triggers `exports is not defined`.
angular = root / "angular.json"
text = angular.read_text()
old = '              "node_modules/leaflet-textpath/leaflet.textpath.js",\n              "node_modules/leaflet-geosearch/lib/index.js"'
new = '              "node_modules/leaflet-textpath/leaflet.textpath.js"'
if text.count(old) != 1:
    raise SystemExit("Expected exactly one redundant leaflet-geosearch global entry")
angular.write_text(text.replace(old, new))

print("Applied three minimal proposed fixes")
