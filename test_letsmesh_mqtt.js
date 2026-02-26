#!/usr/bin/env node
// ============================================================================
// LetsMesh MQTT Auth Diagnostic Tool
// ============================================================================
// Leest ~/.meshcore-gui/device_identity.json automatisch.
// Geen seriële poort nodig — draait naast de daemon.
//
// Gebruik: NODE_PATH=/usr/lib/node_modules node test_letsmesh_mqtt.js
// ============================================================================

const fs = require('fs');
const path = require('path');
const os = require('os');

// ── Identity file laden ─────────────────────────────────────────────────────
const IDENTITY_PATH = path.join(os.homedir(), '.meshcore-gui', 'device_identity.json');

let identity;
try {
  const raw = fs.readFileSync(IDENTITY_PATH, 'utf8');
  identity = JSON.parse(raw);
} catch (e) {
  console.error('❌ Kan ' + IDENTITY_PATH + ' niet lezen: ' + e.message);
  process.exit(1);
}

const seed      = (identity.private_key || '').toLowerCase().trim();
const pubKey    = (identity.public_key  || '').toUpperCase().trim();
const devName   = identity.device_name  || 'onbekend';

// ── Broker configuratie ─────────────────────────────────────────────────────
// Pas aan als je de US broker wilt testen:
//   BROKER_HOST = 'mqtt-us-v1.letsmesh.net'
//   BROKER_AUDIENCE = 'mqtt-us-v1.letsmesh.net'
const BROKER_HOST     = 'mqtt-eu-v1.letsmesh.net';
const BROKER_PORT     = 443;
const BROKER_AUDIENCE = 'mqtt-eu-v1.letsmesh.net';

// ── Validatie ───────────────────────────────────────────────────────────────
function validate() {
  let ok = true;

  console.log('=== LetsMesh MQTT Auth Diagnostic ===\n');
  console.log('Device:    ' + devName);
  console.log('Identity:  ' + IDENTITY_PATH);
  console.log('Broker:    wss://' + BROKER_HOST + ':' + BROKER_PORT + '/mqtt');
  console.log('Audience:  ' + BROKER_AUDIENCE);
  console.log('');

  if (!seed || seed.length !== 64) {
    console.error('❌ private_key (seed) moet 64 hex chars zijn, is: ' + seed.length);
    ok = false;
  } else {
    console.log('Seed:      ' + seed.substring(0, 8) + '...' + seed.substring(56) + ' (' + seed.length + ' chars) ✓');
  }

  if (!pubKey || pubKey.length !== 64) {
    console.error('❌ public_key moet 64 hex chars zijn, is: ' + pubKey.length);
    ok = false;
  } else {
    console.log('Public:    ' + pubKey.substring(0, 8) + '...' + pubKey.substring(56) + ' (' + pubKey.length + ' chars) ✓');
  }

  // MeshCore private key = seed (32 bytes) + public key (32 bytes) = 128 hex
  const privFull = seed + pubKey.toLowerCase();
  console.log('Priv full: ' + privFull.length + ' chars (verwacht: 128) ' + (privFull.length === 128 ? '✓' : '❌'));
  console.log('');

  if (!ok) process.exit(1);
  return privFull;
}

// ── Hoofdprogramma ──────────────────────────────────────────────────────────
async function main() {
  const privFull = validate();

  // ── Token generatie ─────────────────────────────────────────────────────
  var createAuthToken;
  try {
    var decoder = require('@michaelhart/meshcore-decoder');
    createAuthToken = decoder.createAuthToken;
    console.log('[1] meshcore-decoder geladen ✓');
  } catch (e) {
    console.error('❌ Kan @michaelhart/meshcore-decoder niet laden.');
    console.error('   npm install -g @michaelhart/meshcore-decoder');
    console.error('   Draai met: NODE_PATH=/usr/lib/node_modules node test_letsmesh_mqtt.js');
    process.exit(1);
  }

  var iat = Math.floor(Date.now() / 1000);
  var payload = {
    publicKey: pubKey,
    aud: BROKER_AUDIENCE,
    iat: iat,
  };
  console.log('    Payload: ' + JSON.stringify(payload));

  var token;
  try {
    token = await createAuthToken(payload, privFull, pubKey);

    // Decode JWT om te inspecteren
    var parts = token.split('.');
    if (parts.length === 3) {
      var header = JSON.parse(Buffer.from(parts[0], 'base64url').toString());
      var body   = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
      console.log('    JWT Header: ' + JSON.stringify(header));
      console.log('    JWT Body:   ' + JSON.stringify(body));
      console.log('    Signature:  ' + parts[2].substring(0, 30) + '...');
    }
    console.log('    ✓ Token gegenereerd\n');
  } catch (e) {
    console.error('❌ Token generatie mislukt: ' + e.message);
    process.exit(1);
  }

  // ── MQTT verbinding ─────────────────────────────────────────────────────
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
  console.log('    Password: <JWT token>');
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

  client.on('connect', function (connack) {
    clearTimeout(timeout);
    console.log('\n✅ VERBONDEN!');
    console.log('   connack: ' + JSON.stringify(connack));
    console.log('\n=== SUCCES ===');
    console.log('Auth werkt. Kopieer deze settings naar je observer config.');
    console.log('Username: ' + username);
    console.log('Audience: ' + BROKER_AUDIENCE);
    client.end();
    process.exit(0);
  });

  client.on('error', function (err) {
    clearTimeout(timeout);
    console.error('\n❌ MQTT Error: ' + err.message);

    if (err.message.includes('Not authorized') || err.code === 5) {
      console.error('\n=== Not authorized — checklist ===');
      console.error('1. Klopt de public key bij de seed?');
      console.error('   → Draai verify_keys.js om dit te testen');
      console.error('2. Probeer de US broker:');
      console.error('   → Pas BROKER_HOST en BROKER_AUDIENCE aan naar mqtt-us-v1.letsmesh.net');
      console.error('3. Is meshcore-decoder up to date?');
      console.error('   → npm update -g @michaelhart/meshcore-decoder');
    }
    client.end(true);
    process.exit(1);
  });
}

main().catch(function (e) {
  console.error('Fatal: ' + e);
  process.exit(1);
});
