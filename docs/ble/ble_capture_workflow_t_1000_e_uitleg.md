# BLE Capture Workflow T1000-e — Uitleg & Achtergrond

> **Note:** Dit document is BLE-specifiek en wordt bewaard als referentie. De huidige GUI gebruikt USB-serieel.

> **Bron:** `ble_capture_workflow_t_1000_e.md`
>
> Dit document is een **verdiepingsdocument** bij het originele technische werkdocument. Het biedt:
> - Didactische uitleg van BLE-concepten en terminologie
> - Achtergrondkennis over GATT-services en hun werking
> - Context om toekomstige BLE-projecten beter te begrijpen
>
> **Doelgroep:** Mezelf, als referentie voor de lange termijn.

---

## 1. Waar gaat dit document over?

Dit document legt de BLE-concepten en terminologie uit achter de communicatie met een **MeshCore T1000-e** radio vanaf een Linux-computer. Het behandelt:

- Hoe BLE-verbindingen werken en hoe ze verschillen van Classic Bluetooth
- Het GATT-servicemodel en de Nordic UART Service (NUS) die MeshCore gebruikt
- Waarom BLE-sessie-ownership belangrijk is en hoe het verbindingsproblemen kan veroorzaken

**De kernboodschap in één zin:**

> Er mag maar **één BLE-client tegelijk** verbonden zijn met de T1000-e. Als iets anders al verbonden is, faalt jouw verbinding.

---

## 2. Begrippen en afkortingen uitgelegd

### 2.1 BLE — Bluetooth Low Energy

BLE is een **zuinige variant van Bluetooth**, ontworpen voor apparaten die maanden of jaren op een batterij moeten werken.

| Eigenschap | Klassiek Bluetooth | BLE |
|------------|-------------------|-----|
| Stroomverbruik | Hoog | Zeer laag |
| Datasnelheid | Hoog | Laag |
| Typisch gebruik | Audio, bestanden | Sensoren, IoT, MeshCore |

**Analogie:** Klassiek Bluetooth is als een telefoongesprek (constant verbonden, veel energie). BLE is als SMS'jes sturen (kort contact wanneer nodig, weinig energie).

---

### 2.2 GATT — Generic Attribute Profile

GATT is de **structuur** waarmee BLE-apparaten hun data aanbieden. Zie het als een **digitaal prikbord** met een vaste indeling:

```
Service (categorie)
  └── Characteristic (specifiek datapunt)
        └── Descriptor (extra configuratie)
```

**Voorbeeld voor MeshCore:**

```
Nordic UART Service (NUS)
  ├── RX Characteristic → berichten van radio naar computer
  └── TX Characteristic → berichten van computer naar radio
```

---

### 2.3 NUS — Nordic UART Service

NUS is een **standaard BLE-service** ontwikkeld door Nordic Semiconductor. Het simuleert een ouderwetse seriële poort (UART) over Bluetooth.

- **RX** (Receive): Data die je **ontvangt** van het apparaat
- **TX** (Transmit): Data die je **verstuurt** naar het apparaat

Let op: RX/TX zijn vanuit het perspectief van de computer, niet van de radio.

#### Is NUS een protocol?

**Nee.** NUS is een **servicespecificatie**, geen protocol. Dit is een belangrijk onderscheid:

| Niveau | Wat is het | Voorbeeld |
|--------|-----------|-----------|
| **Protocol** | Regels voor communicatie | BLE, ATT, GATT |
| **Service** | Verzameling van gerelateerde characteristics | NUS, Heart Rate Service |
| **Characteristic** | Specifiek datapunt binnen een service | RX, TX |

**Analogie met een restaurant:**

| Concept | Restaurant-analogie |
|---------|---------------------|
| **Protocol (GATT)** | De regels: je bestelt bij de ober, eten komt uit de keuken |
| **Service (NUS)** | Een specifieke menukaart (bijv. "ontbijtmenu") |
| **Characteristics** | De individuele gerechten op dat menu |

Mensen zeggen vaak "we gebruiken het NUS-protocol", maar strikt genomen is **GATT** het protocol en is **NUS** een service die via GATT wordt aangeboden.

---

### 2.4 Andere GATT-services (officieel en custom)

NUS is slechts één van vele BLE-services. De **Bluetooth SIG** (de organisatie achter Bluetooth) definieert tientallen officiële services. Daarnaast kunnen fabrikanten eigen (custom) services maken.

#### Officiële services (Bluetooth SIG)

Deze services hebben een **16-bit UUID** en zijn gestandaardiseerd voor interoperabiliteit:

| Service | UUID | Toepassing |
|---------|------|------------|
| **Heart Rate Service** | 0x180D | Hartslagmeters, fitnessapparaten |
| **Battery Service** | 0x180F | Batterijniveau rapporteren |
| **Device Information** | 0x180A | Fabrikant, modelnummer, firmwareversie |
| **Blood Pressure** | 0x1810 | Bloeddrukmeters |
| **Health Thermometer** | 0x1809 | Medische thermometers |
| **Cycling Speed and Cadence** | 0x1816 | Fietssensoren |
| **Environmental Sensing** | 0x181A | Temperatuur, luchtvochtigheid, druk |
| **Glucose** | 0x1808 | Bloedglucosemeters |
| **HID over GATT** | 0x1812 | Toetsenborden, muizen, gamepads |
| **Proximity** | 0x1802 | "Find My"-functionaliteit |
| **Generic Access** | 0x1800 | **Verplicht** — apparaatnaam en uiterlijk |

#### Custom/vendor-specific services

Fabrikanten kunnen eigen services definiëren met een **128-bit UUID**. Voorbeelden:

| Service | Fabrikant | Toepassing |
|---------|-----------|------------|
| **Nordic UART Service (NUS)** | Nordic Semiconductor | Seriële poort over BLE |
| **Apple Notification Center** | Apple | iPhone notificaties naar wearables |
| **Xiaomi Mi Band Service** | Xiaomi | Fitnesstracker communicatie |
| **MeshCore Companion** | MeshCore | Radio-communicatie (gebruikt NUS) |

#### Het verschil: 16-bit vs. 128-bit UUID

| Type | Lengte | Voorbeeld | Wie mag het maken? |
|------|--------|-----------|-------------------|
| **Officieel (SIG)** | 16-bit | `0x180D` | Alleen Bluetooth SIG |
| **Custom** | 128-bit | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | Iedereen |

De NUS-service gebruikt bijvoorbeeld deze 128-bit UUID:
```
6e400001-b5a3-f393-e0a9-e50e24dcca9e
```

#### Waarom dit relevant is

In het MeshCore-project gebruiken we **NUS** (een custom service) voor de communicatie. Maar als je met andere BLE-apparaten werkt — zoals een hartslagmeter of een slimme thermostaat — dan gebruiken die vaak **officiële SIG-services**.

Het principe blijft hetzelfde:
1. Ontdek welke services het apparaat aanbiedt
2. Zoek de juiste characteristic
3. Lees, schrijf, of abonneer op notify

---

### 2.5 Notify vs. Read

Er zijn twee manieren om data van een BLE-apparaat te krijgen:

| Methode | Werking | Wanneer gebruiken |
|---------|---------|-------------------|
| **Read** | Jij vraagt actief om data | Eenmalige waarden (bijv. batterijstatus) |
| **Notify** | Apparaat stuurt automatisch bij nieuwe data | Continue datastroom (bijv. berichten) |

**Analogie:**
- **Read** = Je belt iemand en vraagt "hoe gaat het?"
- **Notify** = Je krijgt automatisch een WhatsApp-bericht als er nieuws is

Voor MeshCore-captures gebruik je **Notify** — je wilt immers weten wanneer er een bericht binnenkomt.

---

### 2.6 CCCD — Client Characteristic Configuration Descriptor

De CCCD is de **aan/uit-schakelaar voor Notify**. Technisch gezien:

1. Jouw computer schrijft een `1` naar de CCCD
2. Het apparaat weet nu: "deze client wil notificaties"
3. Bij nieuwe data stuurt het apparaat automatisch een bericht

**Het cruciale punt:** Slechts **één client tegelijk** kan de CCCD activeren. Een tweede client krijgt de foutmelding:

```
Notify acquired
```

Dit betekent: "iemand anders heeft notify al ingeschakeld."

---

### 2.7 Pairing, Bonding en Trust

Dit zijn drie afzonderlijke stappen in het BLE-beveiligingsproces:

| Stap | Wat gebeurt er | Analogie |
|------|----------------|----------|
| **Pairing** | Apparaten wisselen cryptografische sleutels uit | Je maakt kennis en wisselt telefoonnummers |
| **Bonding** | De sleutels worden permanent opgeslagen | Je slaat het nummer op in je contacten |
| **Trust** | Het systeem vertrouwt het apparaat automatisch | Je zet iemand in je favorieten |

Na deze drie stappen hoef je niet elke keer opnieuw de pincode in te voeren.

**Controle in Linux:**

```bash
bluetoothctl info literal:AA:BB:CC:DD:EE:FF | egrep -i "Paired|Bonded|Trusted"
```

Verwachte output:

```
Paired: yes
Bonded: yes
Trusted: yes
```

---

### 2.8 Ownership — Het kernprobleem

**Ownership** is een informele term die aangeeft: "welke client heeft op dit moment de actieve GATT-sessie met notify?"

**Analogie:** Denk aan een walkietalkie waarbij maar één persoon tegelijk kan luisteren:

- Als GNOME Bluetooth Manager al verbonden is → die is de "eigenaar"
- Als jouw Python-script daarna probeert te verbinden → krijgt het geen toegang

**Typische "eigenaren" die problemen veroorzaken:**

- GNOME Bluetooth GUI (draait vaak op de achtergrond)
- `bluetoothctl connect` (maakt bluetoothctl de eigenaar)
- Telefoon met Bluetooth aan
- Andere BLE-apps

---

### 2.9 BlueZ

**BlueZ** is de officiële Bluetooth-stack voor Linux. Het is de software die alle Bluetooth-communicatie afhandelt tussen je applicaties en de hardware.

---

### 2.10 Bleak

**Bleak** is een Python-bibliotheek voor BLE-communicatie. Het bouwt voort op BlueZ (Linux), Core Bluetooth (macOS) of WinRT (Windows).

---

## 3. BLE versus Classic Bluetooth

Een veelvoorkomende vraag: zijn BLE en "gewone" Bluetooth hetzelfde? Het antwoord is **nee** — het zijn verschillende technologieën die wel dezelfde naam en frequentieband delen.

### 3.1 Twee smaken van Bluetooth

Sinds Bluetooth 4.0 (2010) zijn er **twee afzonderlijke radiosystemen** binnen de Bluetooth-standaard:

| Naam | Technische term | Kenmerken |
|------|-----------------|-----------|
| **Classic Bluetooth** | BR/EDR (Basic Rate / Enhanced Data Rate) | Hoge datasnelheid, continue verbinding, meer stroom |
| **Bluetooth Low Energy** | BLE (ook: Bluetooth Smart) | Lage datasnelheid, korte bursts, zeer zuinig |

**Cruciaal:** Dit zijn **verschillende radioprotocollen** die niet rechtstreeks met elkaar kunnen communiceren.

### 3.2 Protocol én hardware

Bluetooth (zowel Classic als BLE) omvat **meerdere lagen** — het is niet alleen een protocol, maar ook hardware:

```
┌─────────────────────────────────────────┐
│            SOFTWARE                     │
│  ┌───────────────────────────────────┐  │
│  │  Applicatie (jouw code)           │  │
│  ├───────────────────────────────────┤  │
│  │  Profielen / GATT Services        │  │
│  ├───────────────────────────────────┤  │
│  │  Protocollen (ATT, L2CAP, etc.)   │  │
│  ├───────────────────────────────────┤  │
│  │  Host Controller Interface (HCI)  │  │  ← Grens software/firmware
│  └───────────────────────────────────┘  │
├─────────────────────────────────────────┤
│            FIRMWARE                     │
│  ┌───────────────────────────────────┐  │
│  │  Link Layer / Controller          │  │
│  └───────────────────────────────────┘  │
├─────────────────────────────────────────┤
│            HARDWARE                     │
│  ┌───────────────────────────────────┐  │
│  │  Radio (2.4 GHz transceiver)      │  │
│  ├───────────────────────────────────┤  │
│  │  Antenne                          │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### 3.3 Waar zit het verschil?

Het verschil zit op **meerdere lagen**, niet alleen protocol:

| Laag | Classic (BR/EDR) | BLE | Verschil in hardware? |
|------|------------------|-----|----------------------|
| **Radio** | GFSK, π/4-DQPSK, 8DPSK | GFSK | **Ja** — andere modulatie |
| **Kanalen** | 79 kanalen, 1 MHz breed | 40 kanalen, 2 MHz breed | **Ja** — andere indeling |
| **Link Layer** | LMP (Link Manager Protocol) | LL (Link Layer) | **Ja** — andere state machine |
| **Protocollen** | L2CAP, RFCOMM, SDP | L2CAP, ATT, GATT | Nee — software |

### 3.4 Dual-mode apparaten

De overlap zit in apparaten die **beide** ondersteunen:

| Apparaattype | Ondersteunt | Voorbeeld |
|--------------|-------------|-----------|
| **Classic-only** | Alleen BR/EDR | Oude headsets, auto-audio |
| **BLE-only** (Bluetooth Smart) | Alleen BLE | Fitnesstrackers, sensoren, T1000-e |
| **Dual-Mode** (Bluetooth Smart Ready) | Beide | Smartphones, laptops, ESP32 |

**Jouw smartphone** is dual-mode: hij kan praten met je klassieke Bluetooth-koptelefoon (BR/EDR) én met je MeshCore T1000-e (BLE).

### 3.5 Praktijkvoorbeelden

| Scenario | Wat wordt gebruikt |
|----------|-------------------|
| Muziek naar je koptelefoon | **Classic** (A2DP profiel) |
| Hartslag van je smartwatch | **BLE** (Heart Rate Service) |
| Bestand naar laptop sturen | **Classic** (OBEX/FTP profiel) |
| MeshCore T1000-e uitlezen | **BLE** (NUS service) |
| Handsfree bellen in auto | **Classic** (HFP profiel) |
| Slimme lamp bedienen | **BLE** (eigen GATT service) |

---

## 4. BLE kanaalindeling en frequency hopping

### 4.1 De 40 BLE-kanalen

De 2.4 GHz ISM-band loopt van **2400 MHz tot 2483.5 MHz** (83.5 MHz breed).

BLE verdeelt dit in **40 kanalen van elk 2 MHz**:

```
2400 MHz                                              2480 MHz
   │                                                      │
   ▼                                                      ▼
   ┌──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┐
   │00│01│02│03│04│05│06│07│08│09│10│11│12│13│14│15│16│17│18│19│...→ 39
   └──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┘
     └──────────────────────────────────────────────────────┘
                         2 MHz per kanaal
```

**Totaal:** 40 × 2 MHz = **80 MHz** gebruikt

### 4.2 Advertising vs. data kanalen

De 40 kanalen zijn niet allemaal gelijk:

| Type | Kanalen | Functie |
|------|---------|---------|
| **Advertising** | 3 (nrs. 37, 38, 39) | Apparaten vinden, verbinding starten |
| **Data** | 37 (nrs. 0-36) | Daadwerkelijke communicatie na verbinding |

De advertising-kanalen zijn strategisch gekozen om **Wi-Fi-interferentie** te vermijden:

```
Wi-Fi kanaal 1        Wi-Fi kanaal 6        Wi-Fi kanaal 11
    │                     │                     │
    ▼                     ▼                     ▼
────████████─────────────█████████────────────████████────
    
BLE:  ▲         ▲                    ▲
     Ch.37    Ch.38                Ch.39
     
     (advertising kanalen zitten tússen de Wi-Fi kanalen)
```

### 4.3 Vergelijking met Classic Bluetooth

| Aspect | Classic (BR/EDR) | BLE |
|--------|------------------|-----|
| **Aantal kanalen** | 79 | 40 |
| **Kanaalbreedte** | 1 MHz | 2 MHz |
| **Totale bandbreedte** | 79 MHz | 80 MHz |
| **Frequency hopping** | Ja, alle 79 | Ja, 37 datakanalen |

Classic heeft **meer maar smallere** kanalen, BLE heeft **minder maar bredere** kanalen.

### 4.4 Frequency hopping: één kanaal tegelijk

**Belangrijk inzicht:** Je gebruikt altijd maar **één kanaal tegelijk**. De 40 kanalen zijn er voor **frequency hopping** — het afwisselend wisselen van kanaal om interferentie te vermijden:

```
Tijd →
        ┌───┐     ┌───┐     ┌───┐     ┌───┐
Ch. 12  │ ▓ │     │   │     │   │     │ ▓ │
        └───┘     └───┘     └───┘     └───┘
        ┌───┐     ┌───┐     ┌───┐     ┌───┐
Ch. 07  │   │     │ ▓ │     │   │     │   │
        └───┘     └───┘     └───┘     └───┘
        ┌───┐     ┌───┐     ┌───┐     ┌───┐
Ch. 31  │   │     │   │     │ ▓ │     │   │
        └───┘     └───┘     └───┘     └───┘
          ↑         ↑         ↑         ↑
        Pakket 1  Pakket 2  Pakket 3  Pakket 4
```

Dit is **geen parallelle communicatie** — het is serieel met wisselende frequentie.

---

## 5. Twee betekenissen van "serieel"

Wanneer we zeggen "NUS is serieel", kan dit verwarring veroorzaken. Het woord "serieel" heeft namelijk **twee verschillende betekenissen** in deze context.

### 5.1 Radio-niveau: altijd serieel

**Alle** draadloze communicatie is serieel op fysiek niveau — je hebt maar **één radiokanaal tegelijk** en bits gaan **na elkaar** de lucht in:

```
Radiogolf:  ▁▂▃▄▅▆▇█▇▆▅▄▃▂▁▂▃▄▅▆▇█▇▆▅▄▃▂▁
            
Bits:       0 1 1 0 1 0 0 1 1 1 0 1 0 0 1 0  → één voor één
```

De 40 kanalen zijn voor **frequency hopping**, niet voor parallel versturen. Dit geldt voor **alle** BLE-services — NUS, Heart Rate, Battery, allemaal.

### 5.2 Data-niveau: NUS simuleert een seriële poort

Wanneer we zeggen "NUS is een seriële service", bedoelen we iets anders:

**NUS simuleert een oude seriële poort (RS-232/UART):**

```
Historisch (jaren '80-'00):

   Computer                    Apparaat
   ┌──────┐    Seriële kabel   ┌──────┐
   │ COM1 │←────────────────→│ UART │
   └──────┘    (RS-232)        └──────┘
   
   Bytes: 0x48 0x65 0x6C 0x6C 0x6F  ("Hello")
          └─────────────────────┘
          Geen structuur, gewoon een stroom bytes
```

**NUS bootst dit na over BLE:**

```
Vandaag:

   Computer                    Apparaat
   ┌──────┐    BLE (NUS)       ┌──────┐
   │ App  │←~~~~~~~~~~~~~~~~~~~~→│ MCU  │
   └──────┘    (draadloos)     └──────┘
   
   Gedraagt zich alsof er een seriële kabel zit
```

### 5.3 Vergelijking: serieel vs. gestructureerd

| Aspect | NUS (serieel) | Heart Rate (gestructureerd) |
|--------|---------------|----------------------------|
| **Radio** | Serieel, frequency hopping | Serieel, frequency hopping |
| **Data** | Ongestructureerde bytestroom | Vaste velden met betekenis |
| **Wie bepaalt formaat?** | Jij (eigen protocol) | Bluetooth SIG (specificatie) |

### 5.4 Analogie: snelweg met rijstroken

Denk aan een **snelweg met 40 rijstroken** (de kanalen):

- Je mag maar **één rijstrook tegelijk** gebruiken
- Je wisselt regelmatig van rijstrook (frequency hopping, om botsingen te vermijden)
- De **vracht** die je vervoert kan verschillen:

| Service | Vracht-analogie |
|---------|-----------------|
| **NUS** | Losse spullen door elkaar (flexibel, maar jij moet uitzoeken wat wat is) |
| **Heart Rate** | Gestandaardiseerde pallets (iedereen weet wat waar zit) |

De **snelweg werkt hetzelfde** — het verschil zit in hoe je de vracht organiseert.

---

## 6. Seriële vs. gestructureerde services (verdieping)

Een belangrijk onderscheid dat vaak over het hoofd wordt gezien: **niet alle BLE-services werken hetzelfde**. Er zijn fundamenteel twee benaderingen.

### 6.1 Seriële services (stream-gebaseerd)

**NUS (Nordic UART Service)** is ontworpen om een **seriële poort te simuleren**:

- Continue datastroom van ruwe bytes
- Geen opgelegde structuur
- Jij bepaalt zelf het formaat en de betekenis

**Analogie:** Een seriële service is als een **telefoonlijn** — je kunt alles zeggen wat je wilt, in elke taal, zonder vaste regels.

```
Voorbeeld NUS-data (MeshCore):
0x01 0x0A 0x48 0x65 0x6C 0x6C 0x6F ...
     └── Betekenis bepaald door MeshCore protocol, niet door BLE
```

### 6.2 Gestructureerde services (veld-gebaseerd)

De meeste officiële SIG-services werken **anders** — ze definiëren **exact** welke bytes wat betekenen:

**Analogie:** Een gestructureerde service is als een **belastingformulier** — elk vakje heeft een vaste betekenis en een voorgeschreven formaat.

#### Voorbeeld: Heart Rate Measurement

```
Byte 0: Flags (bitfield)
        ├── Bit 0: 0 = hartslag in 1 byte, 1 = hartslag in 2 bytes
        ├── Bit 1-2: Sensor contact status
        ├── Bit 3: Energy expended aanwezig?
        └── Bit 4: RR-interval aanwezig?

Byte 1(-2): Heart rate waarde
Byte N...: Optionele extra velden (afhankelijk van flags)
```

**Concreet voorbeeld:**

```
Ontvangen bytes: 0x00 0x73

0x00 = Flags: 8-bit formaat, geen extra velden
0x73 = 115 decimaal → hartslag is 115 bpm
```

Je krijgt dus niet de tekst "115", maar een binair pakket dat je moet **parsen** volgens de specificatie.

#### Voorbeeld: Battery Level

Eenvoudiger — slechts **1 byte**:

```
Ontvangen byte: 0x5A

0x5A = 90 decimaal → batterij is 90%
```

#### Voorbeeld: Environmental Sensing (temperatuur)

```
Ontvangen bytes: 0x9C 0x08

Little-endian 16-bit signed integer: 0x089C = 2204
Resolutie: 0.01°C
Temperatuur: 2204 × 0.01 = 22.04°C
```

### 6.3 Vergelijkingstabel

| Aspect | Serieel (NUS) | Gestructureerd (SIG) |
|--------|---------------|----------------------|
| **Data-indeling** | Vrij, zelf bepalen | Vast, door specificatie |
| **Wie definieert het formaat?** | Jij / de fabrikant | Bluetooth SIG |
| **Waar vind je de specificatie?** | Eigen documentatie / broncode | bluetooth.com/specifications |
| **Parsing** | Eigen parser bouwen | Standaard parser mogelijk |
| **Interoperabiliteit** | Alleen eigen software | Elke conforme app/device |
| **Flexibiliteit** | Maximaal | Beperkt tot spec |
| **Complexiteit** | Eenvoudig te starten | Spec lezen vereist |

### 6.4 Voorbeelden van gestructureerde services

| Service | Characteristic | Data-formaat |
|---------|----------------|--------------|
| **Battery Service** | Battery Level | 1 byte: 0-100 (percentage) |
| **Heart Rate** | Heart Rate Measurement | Flags + 8/16-bit HR + optionele velden |
| **Health Thermometer** | Temperature Measurement | IEEE-11073 FLOAT (4 bytes) |
| **Blood Pressure** | Blood Pressure Measurement | Compound: systolisch, diastolisch, MAP, pulse |
| **Cycling Speed & Cadence** | CSC Measurement | 32-bit tellers + 16-bit tijd |
| **Environmental Sensing** | Temperature | 16-bit signed, resolutie 0.01°C |
| **Environmental Sensing** | Humidity | 16-bit unsigned, resolutie 0.01% |
| **Environmental Sensing** | Pressure | 32-bit unsigned, resolutie 0.1 Pa |

### 6.5 Wanneer welke aanpak?

| Situatie | Aanbevolen aanpak |
|----------|-------------------|
| Eigen protocol (MeshCore, custom IoT) | **Serieel** (NUS of eigen service) |
| Standaard use-case (hartslag, batterij) | **Gestructureerd** (SIG-service) |
| Interoperabiliteit met bestaande apps vereist | **Gestructureerd** (SIG-service) |
| Complexe, variabele datastructuren | **Serieel** met eigen protocol |
| Snel prototype zonder spec-studie | **Serieel** (NUS) |

### 6.6 Waarom MeshCore NUS gebruikt

MeshCore koos voor NUS (serieel) omdat:

1. **Flexibiliteit** — Het Companion Protocol heeft eigen framing nodig
2. **Geen passende SIG-service** — Er is geen "Mesh Radio Service" standaard
3. **Bidirectionele communicatie** — NUS biedt RX én TX characteristics
4. **Eenvoud** — Geen complexe SIG-specificatie implementeren

Het nadeel: je kunt niet zomaar een willekeurige BLE-app gebruiken om met MeshCore te praten — je hebt software nodig die het MeshCore Companion Protocol begrijpt.

---

## 7. Het OSI-model in context

Het document plaatst het probleem in een **lagenmodel**. Dit helpt begrijpen *waar* het probleem zit:

| Laag | Naam | In dit project | Probleem hier? |
|------|------|----------------|----------------|
| 7 | Applicatie | MeshCore Companion Protocol | Nee |
| 6 | Presentatie | Frame-encoding (hex) | Nee |
| **5** | **Sessie** | **GATT client ↔ server sessie** | **★ JA** |
| 4 | Transport | ATT / GATT | Nee |
| 2 | Data Link | BLE Link Layer | Nee |
| 1 | Fysiek | 2.4 GHz radio | Nee |

**Conclusie:** Het ownership-probleem zit op **laag 5 (sessie)**. De firmware en het protocol zijn niet het probleem — het gaat om wie de sessie "bezit".

---

## 8. Conclusie

De belangrijkste inzichten uit dit document:

- ✅ MeshCore BLE companion **werkt correct** op Linux
- ✅ De firmware **blokkeert notify niet**
- ✅ Het enige vereiste is: **exact één actieve BLE-client per radio**

Het begrijpen van het ownership-model en de BLE-fundamenten uit dit document is essentieel voor het werken met elk BLE-verbonden MeshCore-apparaat.

---

## 9. Referenties

- MeshCore Companion Radio Protocol: [GitHub Wiki](https://github.com/meshcore-dev/MeshCore/wiki/Companion-Radio-Protocol)
- Bluetooth SIG Assigned Numbers (officiële services): [bluetooth.com/specifications/assigned-numbers](https://www.bluetooth.com/specifications/assigned-numbers/)
- Bluetooth SIG GATT Specifications: [bluetooth.com/specifications/specs](https://www.bluetooth.com/specifications/specs/)
- Nordic Bluetooth Numbers Database: [GitHub](https://github.com/NordicSemiconductor/bluetooth-numbers-database)
- GATT Uitleg (Adafruit): [learn.adafruit.com](https://learn.adafruit.com/introduction-to-bluetooth-low-energy/gatt)
- Bleak documentatie: [bleak.readthedocs.io](https://bleak.readthedocs.io/)
- BlueZ: [bluez.org](http://www.bluez.org/)

---

> **Document:** `ble_capture_workflow_t_1000_e_uitleg.md`
> **Gebaseerd op:** `ble_capture_workflow_t_1000_e.md`
