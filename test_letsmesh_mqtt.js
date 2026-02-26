#!/usr/bin/env node
// ============================================================================
// LetsMesh MQTT Auth Diagnostic Tool
// ============================================================================
// Leest ~/.meshcore-gui/device_identity.json automatisch.
// Geen seriële poort nodig — draait naast de daemon.
//
// Gebruik: NODE_PATH=/usr/lib/node_modules node test_letsmesh_mqtt.js
// ============================================================================

var fs = require('fs');
var path = require('path');
var os = require('os');

// ── Identity file laden ─────────────────────────────────────────────────────
var IDENTITY_PATH = path.join(os.homedir(), '.meshcore-gui', 'device_identity.json');

var identity;
try {
  var raw = fs.readFileSync(IDENTITY_PATH, 'utf8');
  identity = JSON.parse(raw);
} catch (e) {
  console.error('❌ Kan ' + IDENTITY_PATH + ' niet lezen: ' + e.message);
  process.exit(1);
}

var privKey = (identity.private_key || '').toLowerCase().trim();
var pubKey  = (identity.public_key  || '').toUpperCase().trim();
var devName = identity.device_name  || 'onbekend';

// ── Broker ──────────────────────────────────────────────────────────────────
var BROKER_HOST     = 'mqtt-eu-v1.letsmesh.net';
var BROKER_PORT     = 443;
var BROKER_AUDIENCE = 'mqtt-eu-v1.letsmesh.net';

// ── Validatie & private key formaat ─────────────────────────────────────────
function validate() {
  console.log('=== LetsMesh MQTT Auth Diagnostic ===\n');
  console.log('Device:    ' + devName);
  console.log('Identity:  ' + IDENTITY_PATH);
  console.log('Broker:    wss://' + BROKER_HOST + ':' + BROKER_PORT + '/mqtt');
  console.log('Audience:  ' + BROKER_AUDIENCE);
  console.log('');

  var ok = true;

  if (!pubKey || pubKey.length !== 64) {
    console.error('❌ public_key moet 64 hex chars zijn, is: ' + pubKey.length);
    ok = false;
  } else {
    console.log('Public:    ' + pubKey.substring(0, 16) + '...' + pubKey.substring(56) + ' ✓');
  }

  // createAuthToken verwacht privateKeyHex van 128 hex chars (64 bytes)
  var privFull;
  if (privKey.length === 128) {
    // Nieuw formaat: volledige 64-byte orlp key
    privFull = privKey;
    console.log('Priv key:  ' + privFull.substring(0, 16) + '... (128 chars, nieuw formaat) ✓');
  } else if (privKey.length === 64) {
    // Oud formaat: alleen seed, combineer met pub
    privFull = privKey + pubKey.toLowerCase();
    console.log('Priv key:  ' + privKey.substring(0, 16) + '... (64 chars, oud formaat → + pub = 128) ✓');
  } else {
    console.error('❌ private_key moet 128 of 64 hex chars zijn, is: ' + privKey.length);
    ok = false;
  }

  console.log('');
  if (!ok) process.exit(1);
  return privFull;
}

// ── Hoofdprogramma ──────────────────────────────────────────────────────────
async function main() {
  var privFull = validate();

  // Token generatie
  var createAuthToken;
  try {
    var decoder = require('@michaelhart/meshcore-decoder');
    createAuthToken = decoder.createAuthToken;
    console.log('[1] meshcore-decoder geladen ✓');
  } catch (e) {
    console.error('❌ Kan @michaelhart/meshcore-decoder niet laden.');
    console.error('   NODE_PATH=/usr/lib/node_modules node test_letsmesh_mqtt.js');
    process.exit(1);
  }

  var payload = {
    publicKey: pubKey,
    aud: BROKER_AUDIENCE,
    iat: Math.floor(Date.now() / 1000),
  };
  console.log('    Payload: ' + JSON.stringify(payload));

  var token;
  try {
    token = await createAuthToken(payload, privFull, pubKey);
    var parts = token.split('.');
    if (parts.length === 3) {
      var header = JSON.parse(Buffer.from(parts[0], 'base64url').toString());
      var body   = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
      console.log('    JWT Header: ' + JSON.stringify(header));
      console.log('    JWT Body:   ' + JSON.stringify(body));
    }
    console.log('    ✓ Token gegenereerd\n');
  } catch (e) {
    console.error('❌ Token generatie mislukt: ' + e.message);
    process.exit(1);
  }

  // MQTT verbinding
  var mqtt;
  try {
    mqtt = require('mqtt');
  } catch (e) {
    console.error('❌ mqtt library niet gevonden. npm install -g mqtt');
    process.exit(1);
  }

  var username = 'v1_' + pubKey;
  console.log('[2] MQTT verbinding...');
  console.log('    Username: ' + username);
  console.log('');

  var url = 'wss://' + BROKER_HOST + ':' + BROKER_PORT + '/mqtt';

  var client = mqtt.connect(url, {
    clientId: 'diag_' + pubKey.substring(0, 8) + '_' + Date.now(),
    username: username,
    password: token,
    protocolVersion: 4,
    keepalive: 60,
    connectTimeout: 15000,
    rejectUnauthorized: true,
  });

  var timeout = setTimeout(function () {
    console.error('\n❌ Timeout na 15 seconden.');
    client.end(true);
    process.exit(1);
  }, 15000);

  client.on('connect', function () {
    clearTimeout(timeout);
    console.log('\n✅ VERBONDEN!');
    console.log('\nUsername: ' + username);
    console.log('Audience: ' + BROKER_AUDIENCE);
    client.end();
    process.exit(0);
  });

  client.on('error', function (err) {
    clearTimeout(timeout);
    console.error('\n❌ MQTT Error: ' + err.message);
    if (err.message.includes('Not authorized')) {
      console.error('\nNog steeds Not authorized. Controleer:');
      console.error('  1. Herstart meshcore_gui zodat device_identity.json opnieuw geschreven wordt');
      console.error('  2. Controleer of public_key in JSON matcht met de GUI');
      console.error('  3. Probeer US broker: verander BROKER_HOST naar mqtt-us-v1.letsmesh.net');
    }
    client.end(true);
    process.exit(1);
  });
}

main().catch(function (e) { console.error('Fatal: ' + e); process.exit(1); });
