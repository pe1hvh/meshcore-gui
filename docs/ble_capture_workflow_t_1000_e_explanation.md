# BLE Capture Workflow T1000-e — Explanation & Background

> **Source:** `ble_capture_workflow_t_1000_e.md`
>
> This document is a **companion guide** to the original technical working document. It provides:
> - Didactic explanation of BLE concepts and terminology
> - Background knowledge about GATT services and how they work
> - Context for better understanding future BLE projects
>
> **Intended audience:** Myself, as a long-term reference.

---

## 1. What is this document about?

The original document describes how to "listen in" on the BLE communication of a **MeshCore T1000-e** radio from a Linux computer. It explains:

- What steps are needed to set up a connection
- Why it often goes wrong (and how to prevent that)
- How to save raw protocol data for analysis

**The key message in one sentence:**

> Only **one listener at a time** can be connected to the T1000-e. If something else is already connected, your capture will fail.

---

## 2. Terms and abbreviations explained

### 2.1 BLE — Bluetooth Low Energy

BLE is an **energy-efficient variant of Bluetooth**, designed for devices that need to run on a battery for months or years.

| Property | Classic Bluetooth | BLE |
|----------|-------------------|-----|
| Power consumption | High | Very low |
| Data rate | High | Low |
| Typical use | Audio, file transfer | Sensors, IoT, MeshCore |

**Analogy:** Classic Bluetooth is like a phone call (constantly connected, high energy). BLE is like sending text messages (brief contact when needed, low energy).

---

### 2.2 GATT — Generic Attribute Profile

GATT is the **structure** through which BLE devices expose their data. Think of it as a **digital bulletin board** with a fixed layout:

```
Service (category)
  └── Characteristic (specific data point)
        └── Descriptor (additional configuration)
```

**Example for MeshCore:**

```
Nordic UART Service (NUS)
  ├── RX Characteristic → messages from radio to computer
  └── TX Characteristic → messages from computer to radio
```

---

### 2.3 NUS — Nordic UART Service

NUS is a **standard BLE service** developed by Nordic Semiconductor. It simulates an old-fashioned serial port (UART) over Bluetooth.

- **RX** (Receive): Data you **receive** from the device
- **TX** (Transmit): Data you **send** to the device

Note: RX/TX are from the computer's perspective, not the radio's.

#### Is NUS a protocol?

**No.** NUS is a **service specification**, not a protocol. This is an important distinction:

| Level | What is it | Example |
|-------|-----------|---------|
| **Protocol** | Rules for communication | BLE, ATT, GATT |
| **Service** | Collection of related characteristics | NUS, Heart Rate Service |
| **Characteristic** | Specific data point within a service | RX, TX |

**Restaurant analogy:**

| Concept | Restaurant analogy |
|---------|--------------------|
| **Protocol (GATT)** | The rules: you order from the waiter, food comes from the kitchen |
| **Service (NUS)** | A specific menu (e.g. "breakfast menu") |
| **Characteristics** | The individual dishes on that menu |

People often say "we're using the NUS protocol", but strictly speaking **GATT** is the protocol and **NUS** is a service offered via GATT.

---

### 2.4 Other GATT services (official and custom)

NUS is just one of many BLE services. The **Bluetooth SIG** (the organisation behind Bluetooth) defines dozens of official services. In addition, manufacturers can create their own (custom) services.

#### Official services (Bluetooth SIG)

These services have a **16-bit UUID** and are standardised for interoperability:

| Service | UUID | Application |
|---------|------|-------------|
| **Heart Rate Service** | 0x180D | Heart rate monitors, fitness devices |
| **Battery Service** | 0x180F | Reporting battery level |
| **Device Information** | 0x180A | Manufacturer, model number, firmware version |
| **Blood Pressure** | 0x1810 | Blood pressure monitors |
| **Health Thermometer** | 0x1809 | Medical thermometers |
| **Cycling Speed and Cadence** | 0x1816 | Bicycle sensors |
| **Environmental Sensing** | 0x181A | Temperature, humidity, pressure |
| **Glucose** | 0x1808 | Blood glucose meters |
| **HID over GATT** | 0x1812 | Keyboards, mice, gamepads |
| **Proximity** | 0x1802 | "Find My" functionality |
| **Generic Access** | 0x1800 | **Mandatory** — device name and appearance |

#### Custom/vendor-specific services

Manufacturers can define their own services with a **128-bit UUID**. Examples:

| Service | Manufacturer | Application |
|---------|--------------|-------------|
| **Nordic UART Service (NUS)** | Nordic Semiconductor | Serial port over BLE |
| **Apple Notification Center** | Apple | iPhone notifications to wearables |
| **Xiaomi Mi Band Service** | Xiaomi | Fitness tracker communication |
| **MeshCore Companion** | MeshCore | Radio communication (uses NUS) |

#### The difference: 16-bit vs. 128-bit UUID

| Type | Length | Example | Who can create it? |
|------|--------|---------|--------------------|
| **Official (SIG)** | 16-bit | `0x180D` | Bluetooth SIG only |
| **Custom** | 128-bit | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | Anyone |

The NUS service uses this 128-bit UUID:
```
6e400001-b5a3-f393-e0a9-e50e24dcca9e
```

#### Why this matters

In the MeshCore project we use **NUS** (a custom service) for communication. But when working with other BLE devices — such as a heart rate monitor or a smart thermostat — they typically use **official SIG services**.

The principle remains the same:
1. Discover which services the device offers
2. Find the right characteristic
3. Read, write, or subscribe to notify

---

### 2.5 Notify vs. Read

There are two ways to get data from a BLE device:

| Method | How it works | When to use |
|--------|-------------|-------------|
| **Read** | You actively request data | One-off values (e.g. battery status) |
| **Notify** | Device sends automatically when new data is available | Continuous data stream (e.g. messages) |

**Analogy:**
- **Read** = You call someone and ask "how are you?"
- **Notify** = You automatically receive a WhatsApp message when there's news

For MeshCore captures you use **Notify** — after all, you want to know when a message arrives.

---

### 2.6 CCCD — Client Characteristic Configuration Descriptor

The CCCD is the **on/off switch for Notify**. Technically:

1. Your computer writes a `1` to the CCCD
2. The device now knows: "this client wants notifications"
3. When new data arrives, the device automatically sends a message

**The crucial point:** Only **one client at a time** can activate the CCCD. A second client will receive the error:

```
Notify acquired
```

This means: "someone else has already enabled notify."

---

### 2.7 Pairing, Bonding and Trust

These are three separate steps in the BLE security process:

| Step | What happens | Analogy |
|------|-------------|---------|
| **Pairing** | Devices exchange cryptographic keys | You meet someone and exchange phone numbers |
| **Bonding** | The keys are stored permanently | You save the number in your contacts |
| **Trust** | The system trusts the device automatically | You add someone to your favourites |

After these three steps, you no longer need to enter the PIN code each time.

**Verification on Linux:**

```bash
bluetoothctl info AA:BB:CC:DD:EE:FF | egrep -i "Paired|Bonded|Trusted"
```

Expected output:

```
Paired: yes
Bonded: yes
Trusted: yes
```

---

### 2.8 Ownership — The core problem

**Ownership** is an informal term indicating: "which client currently holds the active GATT session with notify?"

**Analogy:** Think of a walkie-talkie where only one person can listen at a time:

- If GNOME Bluetooth Manager is already connected → it is the "owner"
- If your Python script then tries to connect → it won't get access

**Typical "owners" that cause problems:**

- GNOME Bluetooth GUI (often runs in the background)
- `bluetoothctl connect` (makes bluetoothctl the owner)
- Phone with Bluetooth enabled
- Other BLE apps

---

### 2.9 BlueZ

**BlueZ** is the official Bluetooth stack for Linux. It is the software that handles all Bluetooth communication between your applications and the hardware.

---

### 2.10 Bleak

**Bleak** is a Python library for BLE communication. It builds on top of BlueZ (Linux), Core Bluetooth (macOS) or WinRT (Windows).

---

## 3. BLE versus Classic Bluetooth

A common question: are BLE and "regular" Bluetooth the same thing? The answer is **no** — they are different technologies that happen to share the same name and frequency band.

### 3.1 Two flavours of Bluetooth

Since Bluetooth 4.0 (2010) there are **two separate radio systems** within the Bluetooth standard:

| Name | Technical term | Characteristics |
|------|---------------|-----------------|
| **Classic Bluetooth** | BR/EDR (Basic Rate / Enhanced Data Rate) | High data rate, continuous connection, more power |
| **Bluetooth Low Energy** | BLE (also: Bluetooth Smart) | Low data rate, short bursts, very efficient |

**Crucially:** These are **different radio protocols** that cannot communicate directly with each other.

### 3.2 Protocol and hardware

Bluetooth (both Classic and BLE) encompasses **multiple layers** — it is not just a protocol, but also hardware:

```
┌─────────────────────────────────────────┐
│            SOFTWARE                     │
│  ┌───────────────────────────────────┐  │
│  │  Application (your code)          │  │
│  ├───────────────────────────────────┤  │
│  │  Profiles / GATT Services         │  │
│  ├───────────────────────────────────┤  │
│  │  Protocols (ATT, L2CAP, etc.)     │  │
│  ├───────────────────────────────────┤  │
│  │  Host Controller Interface (HCI)  │  │  ← Software/firmware boundary
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
│  │  Antenna                          │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### 3.3 Where is the difference?

The difference exists across **multiple layers**, not just the protocol:

| Layer | Classic (BR/EDR) | BLE | Hardware difference? |
|-------|------------------|-----|---------------------|
| **Radio** | GFSK, π/4-DQPSK, 8DPSK | GFSK | **Yes** — different modulation |
| **Channels** | 79 channels, 1 MHz wide | 40 channels, 2 MHz wide | **Yes** — different layout |
| **Link Layer** | LMP (Link Manager Protocol) | LL (Link Layer) | **Yes** — different state machine |
| **Protocols** | L2CAP, RFCOMM, SDP | L2CAP, ATT, GATT | No — software |

### 3.4 Dual-mode devices

The overlap lies in devices that support **both**:

| Device type | Supports | Example |
|-------------|----------|---------|
| **Classic-only** | BR/EDR only | Old headsets, car audio |
| **BLE-only** (Bluetooth Smart) | BLE only | Fitness trackers, sensors, T1000-e |
| **Dual-Mode** (Bluetooth Smart Ready) | Both | Smartphones, laptops, ESP32 |

**Your smartphone** is dual-mode: it can talk to your classic Bluetooth headphones (BR/EDR) and to your MeshCore T1000-e (BLE).

### 3.5 Practical examples

| Scenario | What is used |
|----------|-------------|
| Music to your headphones | **Classic** (A2DP profile) |
| Heart rate from your smartwatch | **BLE** (Heart Rate Service) |
| Sending a file to a laptop | **Classic** (OBEX/FTP profile) |
| Reading the MeshCore T1000-e | **BLE** (NUS service) |
| Hands-free calling in the car | **Classic** (HFP profile) |
| Controlling a smart light | **BLE** (custom GATT service) |

---

## 4. BLE channel layout and frequency hopping

### 4.1 The 40 BLE channels

The 2.4 GHz ISM band runs from **2400 MHz to 2483.5 MHz** (83.5 MHz wide).

BLE divides this into **40 channels of 2 MHz each**:

```
2400 MHz                                              2480 MHz
   │                                                      │
   ▼                                                      ▼
   ┌──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┐
   │00│01│02│03│04│05│06│07│08│09│10│11│12│13│14│15│16│17│18│19│...→ 39
   └──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┘
     └──────────────────────────────────────────────────────┘
                         2 MHz per channel
```

**Total:** 40 × 2 MHz = **80 MHz** used

### 4.2 Advertising vs. data channels

The 40 channels are not all equal:

| Type | Channels | Function |
|------|----------|----------|
| **Advertising** | 3 (nos. 37, 38, 39) | Device discovery, initiating connections |
| **Data** | 37 (nos. 0-36) | Actual communication after connection |

The advertising channels are strategically chosen to **avoid Wi-Fi interference**:

```
Wi-Fi channel 1       Wi-Fi channel 6       Wi-Fi channel 11
    │                     │                     │
    ▼                     ▼                     ▼
────████████─────────────█████████────────────████████────
    
BLE:  ▲         ▲                    ▲
     Ch.37    Ch.38                Ch.39
     
     (advertising channels sit between the Wi-Fi channels)
```

### 4.3 Comparison with Classic Bluetooth

| Aspect | Classic (BR/EDR) | BLE |
|--------|------------------|-----|
| **Number of channels** | 79 | 40 |
| **Channel width** | 1 MHz | 2 MHz |
| **Total bandwidth** | 79 MHz | 80 MHz |
| **Frequency hopping** | Yes, all 79 | Yes, 37 data channels |

Classic has **more but narrower** channels, BLE has **fewer but wider** channels.

### 4.4 Frequency hopping: one channel at a time

**Key insight:** You only ever use **one channel at a time**. The 40 channels exist for **frequency hopping** — alternately switching channels to avoid interference:

```
Time →
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
        Packet 1  Packet 2  Packet 3  Packet 4
```

This is **not parallel communication** — it is serial with alternating frequencies.

---

## 5. Two meanings of "serial"

When we say "NUS is serial", this can cause confusion. The word "serial" has **two different meanings** in this context.

### 5.1 Radio level: always serial

**All** wireless communication is serial at the physical level — you only have **one radio channel at a time** and bits go into the air **one after another**:

```
Radio wave:  ▁▂▃▄▅▆▇█▇▆▅▄▃▂▁▂▃▄▅▆▇█▇▆▅▄▃▂▁

Bits:        0 1 1 0 1 0 0 1 1 1 0 1 0 0 1 0  → one by one
```

The 40 channels are for **frequency hopping**, not for parallel transmission. This applies to **all** BLE services — NUS, Heart Rate, Battery, all of them.

### 5.2 Data level: NUS simulates a serial port

When we say "NUS is a serial service", we mean something different:

**NUS simulates an old serial port (RS-232/UART):**

```
Historical (1980s-2000s):

   Computer                    Device
   ┌──────┐    Serial cable    ┌──────┐
   │ COM1 │←────────────────→│ UART │
   └──────┘    (RS-232)        └──────┘
   
   Bytes: 0x48 0x65 0x6C 0x6C 0x6F  ("Hello")
          └─────────────────────┘
          No structure, just a stream of bytes
```

**NUS mimics this over BLE:**

```
Today:

   Computer                    Device
   ┌──────┐    BLE (NUS)       ┌──────┐
   │ App  │←~~~~~~~~~~~~~~~~~~~~→│ MCU  │
   └──────┘    (wireless)      └──────┘
   
   Behaves as if there were a serial cable
```

### 5.3 Comparison: serial vs. structured

| Aspect | NUS (serial) | Heart Rate (structured) |
|--------|-------------|------------------------|
| **Radio** | Serial, frequency hopping | Serial, frequency hopping |
| **Data** | Unstructured byte stream | Fixed fields with meaning |
| **Who determines the format?** | You (custom protocol) | Bluetooth SIG (specification) |

### 5.4 Analogy: motorway with lanes

Think of a **motorway with 40 lanes** (the channels):

- You may only use **one lane at a time**
- You regularly switch lanes (frequency hopping, to avoid collisions)
- The **cargo** you transport can differ:

| Service | Cargo analogy |
|---------|--------------|
| **NUS** | Loose items mixed together (flexible, but you need to figure out what's what) |
| **Heart Rate** | Standardised pallets (everyone knows what goes where) |

The **motorway works the same** — the difference lies in how you organise the cargo.

---

## 6. Serial vs. structured services (deep dive)

An important distinction that is often overlooked: **not all BLE services work the same way**. There are fundamentally two approaches.

### 6.1 Serial services (stream-based)

**NUS (Nordic UART Service)** is designed to **simulate a serial port**:

- Continuous stream of raw bytes
- No imposed structure
- You determine the format and meaning yourself

**Analogy:** A serial service is like a **phone line** — you can say whatever you want, in any language, without fixed rules.

```
Example NUS data (MeshCore):
0x01 0x0A 0x48 0x65 0x6C 0x6C 0x6F ...
     └── Meaning determined by MeshCore protocol, not by BLE
```

### 6.2 Structured services (field-based)

Most official SIG services work **differently** — they define **exactly** which bytes mean what:

**Analogy:** A structured service is like a **tax form** — each field has a fixed meaning and a prescribed format.

#### Example: Heart Rate Measurement

```
Byte 0: Flags (bitfield)
        ├── Bit 0: 0 = heart rate in 1 byte, 1 = heart rate in 2 bytes
        ├── Bit 1-2: Sensor contact status
        ├── Bit 3: Energy expended present?
        └── Bit 4: RR-interval present?

Byte 1(-2): Heart rate value
Byte N...: Optional additional fields (depending on flags)
```

**Concrete example:**

```
Received bytes: 0x00 0x73

0x00 = Flags: 8-bit format, no additional fields
0x73 = 115 decimal → heart rate is 115 bpm
```

So you don't receive the text "115", but a binary packet that you need to **parse** according to the specification.

#### Example: Battery Level

Simpler — just **1 byte**:

```
Received byte: 0x5A

0x5A = 90 decimal → battery is 90%
```

#### Example: Environmental Sensing (temperature)

```
Received bytes: 0x9C 0x08

Little-endian 16-bit signed integer: 0x089C = 2204
Resolution: 0.01°C
Temperature: 2204 × 0.01 = 22.04°C
```

### 6.3 Comparison table

| Aspect | Serial (NUS) | Structured (SIG) |
|--------|-------------|------------------|
| **Data format** | Free, self-determined | Fixed, by specification |
| **Who defines the format?** | You / the manufacturer | Bluetooth SIG |
| **Where to find the spec?** | Own documentation / source code | bluetooth.com/specifications |
| **Parsing** | Build your own parser | Standard parser possible |
| **Interoperability** | Own software only | Any conformant app/device |
| **Flexibility** | Maximum | Limited to spec |
| **Complexity** | Easy to get started | Reading the spec required |

### 6.4 Examples of structured services

| Service | Characteristic | Data format |
|---------|----------------|-------------|
| **Battery Service** | Battery Level | 1 byte: 0-100 (percentage) |
| **Heart Rate** | Heart Rate Measurement | Flags + 8/16-bit HR + optional fields |
| **Health Thermometer** | Temperature Measurement | IEEE-11073 FLOAT (4 bytes) |
| **Blood Pressure** | Blood Pressure Measurement | Compound: systolic, diastolic, MAP, pulse |
| **Cycling Speed & Cadence** | CSC Measurement | 32-bit counters + 16-bit time |
| **Environmental Sensing** | Temperature | 16-bit signed, resolution 0.01°C |
| **Environmental Sensing** | Humidity | 16-bit unsigned, resolution 0.01% |
| **Environmental Sensing** | Pressure | 32-bit unsigned, resolution 0.1 Pa |

### 6.5 When to use which approach?

| Situation | Recommended approach |
|-----------|---------------------|
| Custom protocol (MeshCore, custom IoT) | **Serial** (NUS or custom service) |
| Standard use case (heart rate, battery) | **Structured** (SIG service) |
| Interoperability with existing apps required | **Structured** (SIG service) |
| Complex, variable data structures | **Serial** with custom protocol |
| Quick prototype without studying specs | **Serial** (NUS) |

### 6.6 Why MeshCore uses NUS

MeshCore chose NUS (serial) because:

1. **Flexibility** — The Companion Protocol requires its own framing
2. **No suitable SIG service** — There is no "Mesh Radio Service" standard
3. **Bidirectional communication** — NUS offers both RX and TX characteristics
4. **Simplicity** — No need to implement a complex SIG specification

The downside: you can't just use any arbitrary BLE app to talk to MeshCore — you need software that understands the MeshCore Companion Protocol.

---

## 7. The OSI model in context

The document places the problem in a **layer model**. This helps understand *where* the problem lies:

| Layer | Name | In this project | Problem here? |
|-------|------|-----------------|---------------|
| 7 | Application | MeshCore Companion Protocol | No |
| 6 | Presentation | Frame encoding (hex) | No |
| **5** | **Session** | **GATT client ↔ server session** | **★ YES** |
| 4 | Transport | ATT / GATT | No |
| 2 | Data Link | BLE Link Layer | No |
| 1 | Physical | 2.4 GHz radio | No |

**Conclusion:** The ownership problem sits at **layer 5 (session)**. The firmware and protocol are not the problem — it's about who "owns" the session.

---

## 8. The workflow summarised

### 8.1 One-time preparation

```bash
# Start bluetoothctl
bluetoothctl

# Activate Bluetooth
power on
agent on
default-agent
scan on

# Wait until device is visible, then pair
pair AA:BB:CC:DD:EE:FF
# Enter PIN code (e.g. 123456)

# Trust the device
trust AA:BB:CC:DD:EE:FF
quit
```

### 8.2 Before each capture

1. **Phone Bluetooth OFF**
2. **Close GNOME Bluetooth GUI**
3. **Explicitly disconnect:**

```bash
bluetoothctl disconnect AA:BB:CC:DD:EE:FF
```

4. **Verify that nothing is connected:**

```bash
bluetoothctl info AA:BB:CC:DD:EE:FF | egrep -i "Connected"
# Expected: Connected: no
```

### 8.3 Starting a capture

```bash
python tools/ble_observe.py \
  --address AA:BB:CC:DD:EE:FF \
  --pre-scan-seconds 10 \
  --connect-timeout 30 \
  --notify \
  --notify-seconds 30 \
  --notify-start-timeout 30 \
  --disconnect-timeout 15 \
  --capture captures/session_$(date -u +%Y-%m-%d_%H%M%S).raw
```

---

## 9. Common mistakes

| Mistake | Consequence | Solution |
|---------|------------|----------|
| GNOME Bluetooth Manager open | `Notify acquired` | Close the GUI |
| Ran `bluetoothctl connect` | Tool fails at notify | Always `disconnect` first |
| Phone Bluetooth on | Phone claims the connection | Turn off phone BT |
| Multiple scripts at once | First one wins, rest fail | One tool at a time |

---

## 10. Visual overview (sequence diagram)

```
┌──────┐     ┌───────┐     ┌───────┐     ┌───────┐
│ User │     │ Linux │     │ BlueZ │     │ Radio │
└──┬───┘     └───┬───┘     └───┬───┘     └───┬───┘
   │             │             │             │
   │ pair/trust  │             │             │
   │────────────>│────────────────────────-->│  (one-time)
   │             │             │             │
   │             │    No active connection   │
   │             │             │             │
   │ start tool  │             │             │
   │────────────>│             │             │
   │             │  connect()  │             │
   │             │────────────>│────────────>│
   │             │             │             │
   │             │start_notify │             │
   │             │────────────>│────────────>│
   │             │             │             │
   │             │    notify (data frames)   │
   │             │<────────────│<────────────│
   │             │             │             │
   │             │ stop_notify │             │
   │             │────────────>│────────────>│
   │             │             │             │
   │             │ disconnect  │             │
   │             │────────────>│────────────>│
   │             │             │             │
```

---

## 11. Conclusion

The document demonstrates that:

- ✅ MeshCore BLE companion **works correctly** on Linux
- ✅ The firmware **does not block notify**
- ✅ The only requirement is: **exactly one active BLE client per radio**

When you follow this workflow, captures are reproducible and further protocol analysis becomes possible.

---

## 12. References

- MeshCore Companion Radio Protocol: [GitHub Wiki](https://github.com/meshcore-dev/MeshCore/wiki/Companion-Radio-Protocol)
- Bluetooth SIG Assigned Numbers (official services): [bluetooth.com/specifications/assigned-numbers](https://www.bluetooth.com/specifications/assigned-numbers/)
- Bluetooth SIG GATT Specifications: [bluetooth.com/specifications/specs](https://www.bluetooth.com/specifications/specs/)
- Nordic Bluetooth Numbers Database: [GitHub](https://github.com/NordicSemiconductor/bluetooth-numbers-database)
- GATT Explanation (Adafruit): [learn.adafruit.com](https://learn.adafruit.com/introduction-to-bluetooth-low-energy/gatt)
- Bleak documentation: [bleak.readthedocs.io](https://bleak.readthedocs.io/)
- BlueZ: [bluez.org](http://www.bluez.org/)

---

> **Document:** `ble_capture_workflow_t_1000_e_explanation.md`
> **Based on:** `ble_capture_workflow_t_1000_e.md`
