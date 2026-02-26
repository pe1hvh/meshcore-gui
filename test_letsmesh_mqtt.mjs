#!/usr/bin/env node
// ============================================================================
// LetsMesh MQTT Auth Diagnostic Tool
// ============================================================================
// Standalone test — geen seriële poort nodig.
// Gebruik: NODE_PATH=/usr/lib/node_modules node test_letsmesh_mqtt.mjs
//
// Vereist:
//   npm install -g @michaelhart/meshcore-decoder mqtt
//   (mqtt client lib: npm install -g mqtt)
// ============================================================================

import { createRequire } from 'module';
const require = createRequire(import.meta.url);

// ── Config ──────────────────────────────────────────────────────────────────
// Pas deze waarden aan vanuit device_identity.json
const DEVICE_PRIVATE_KEY = 'ab520964a364bd088359e67150da6c1d71fbd9f57cf75e392b0926cf8aff608f';  // 32-byte seed (64 hex)
// De public key moet afgeleid worden — vul hier de juiste uppercase hex in:
const DEVICE_PUBLIC_KEY  = '';  // <-- VUL IN: 64 hex chars uppercase, uit device_identity.json

// Broker settings
const BROKER_HOST = 'mqtt-eu-v1.letsmesh.net';
const BROKER_PORT = 443;
const BROKER_AUDIENCE = 'mqtt-eu-v1.letsmesh.net';
// ────────────────────────────────────────────────────────────────────────────

async function main() {
  console.log('=== LetsMesh MQTT Auth Diagnostic ===\n');

  // ── Stap 0: Validatie ───────────────────────────────────────────────────
  if (!DEVICE_PUBLIC_KEY || DEVICE_PUBLIC_KEY.length !== 64) {
    console.error('❌ DEVICE_PUBLIC_KEY is niet ingevuld of niet 64 hex chars.');
    console.error('   Open ~/.meshcore-gui/device_identity.json en kopieer public_key.');
    console.error('   Zorg dat het UPPERCASE is.');
    process.exit(1);
  }

  const pubKeyUpper = DEVICE_PUBLIC_KEY.toUpperCase();
  const seedHex = DEVICE_PRIVATE_KEY.toLowerCase();

  console.log(`Device public key:  ${pubKeyUpper}`);
  console.log(`Device seed (priv): ${seedHex.substring(0, 8)}...${seedHex.substring(56)}`);
  console.log(`Broker:             wss://${BROKER_HOST}:${BROKER_PORT}/mqtt`);
  console.log(`Audience:           ${BROKER_AUDIENCE}`);
  console.log();

  // ── Stap 1: Private key formaat (128 hex = seed + pub) ──────────────────
  // MeshCore formaat: 64 bytes = 32-byte seed + 32-byte public key
  const privateKeyFull = seedHex + pubKeyUpper.toLowerCase();
  console.log(`[1] Private key (MeshCore format, 128 hex): ${privateKeyFull.substring(0, 8)}...${privateKeyFull.substring(120)}`);
  console.log(`    Length: ${privateKeyFull.length} chars (verwacht: 128)`);
  if (privateKeyFull.length !== 128) {
    console.error('❌ Private key moet exact 128 hex chars zijn (seed + pub)');
    process.exit(1);
  }
  console.log('    ✓ Formaat OK\n');

  // ── Stap 2: Token generatie met meshcore-decoder ────────────────────────
  let createAuthToken;
  try {
    const decoder = require('@michaelhart/meshcore-decoder');
    createAuthToken = decoder.createAuthToken;
    console.log('[2] meshcore-decoder geladen ✓');
  } catch (e) {
    console.error('❌ Kan @michaelhart/meshcore-decoder niet laden.');
    console.error('   Installeer: npm install -g @michaelhart/meshcore-decoder');
    console.error('   En draai met: NODE_PATH=/usr/lib/node_modules node test_letsmesh_mqtt.mjs');
    process.exit(1);
  }

  const iat = Math.floor(Date.now() / 1000);
  const payload = {
    publicKey: pubKeyUpper,
    aud: BROKER_AUDIENCE,
    iat: iat,
  };

  console.log(`    Payload: ${JSON.stringify(payload)}`);

  let token;
  try {
    token = await createAuthToken(payload, privateKeyFull, pubKeyUpper);
    console.log(`    Token (eerste 60 chars): ${token.substring(0, 60)}...`);

    // Decode de token om te inspecteren
    const parts = token.split('.');
    if (parts.length === 3) {
      const header = JSON.parse(Buffer.from(parts[0], 'base64url').toString());
      const body = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
      console.log(`    JWT Header: ${JSON.stringify(header)}`);
      console.log(`    JWT Body:   ${JSON.stringify(body)}`);
      console.log(`    Signature:  ${parts[2].substring(0, 30)}...`);
    }
    console.log('    ✓ Token gegenereerd\n');
  } catch (e) {
    console.error(`❌ Token generatie mislukt: ${e.message}`);
    console.error('   Controleer of de private key klopt.');
    process.exit(1);
  }

  // ── Stap 3: MQTT verbinding ─────────────────────────────────────────────
  const username = `v1_${pubKeyUpper}`;
  console.log(`[3] MQTT verbinding...`);
  console.log(`    Username: ${username}`);
  console.log(`    Password: <JWT token>`);

  let mqtt;
  try {
    mqtt = require('mqtt');
  } catch (e) {
    console.error('❌ mqtt library niet gevonden.');
    console.error('   Installeer: npm install -g mqtt');
    process.exit(1);
  }

  const url = `wss://${BROKER_HOST}:${BROKER_PORT}/mqtt`;

  const client = mqtt.connect(url, {
    clientId: `diag_${pubKeyUpper.substring(0, 8)}_${Date.now()}`,
    username: username,
    password: token,
    protocolVersion: 4,        // MQTT 3.1.1
    keepalive: 60,
    connectTimeout: 15000,
    rejectUnauthorized: true,   // TLS cert verificatie
  });

  const timeout = setTimeout(() => {
    console.error('\n❌ Timeout na 15 seconden — geen reactie van broker.');
    client.end(true);
    process.exit(1);
  }, 15000);

  client.on('connect', (connack) => {
    clearTimeout(timeout);
    console.log('\n✅ VERBONDEN! connack:', JSON.stringify(connack));
    console.log('\n=== SUCCES ===');
    console.log('De authenticatie werkt. Het probleem zit in de observer code, niet in de keys.');
    client.end();
    process.exit(0);
  });

  client.on('error', (err) => {
    clearTimeout(timeout);
    console.error(`\n❌ MQTT Error: ${err.message}`);
    if (err.message.includes('Not authorized') || err.code === 5) {
      console.error('\n=== DIAGNOSE: Not authorized ===');
      console.error('De broker weigert de credentials. Mogelijke oorzaken:');
      console.error('  1. Public key in uppercase? Check: ' + (pubKeyUpper === DEVICE_PUBLIC_KEY ? 'JA ✓' : 'NEE ❌ — was lowercase!'));
      console.error('  2. Audience exact goed? Huidig: ' + BROKER_AUDIENCE);
      console.error('  3. Private key correct format? seed+pub = 128 hex');
      console.error('  4. Klopt de public key bij de private key (seed)?');
      console.error('');
      console.error('Test: Probeer ook de US broker:');
      console.error('  Verander BROKER_HOST naar mqtt-us-v1.letsmesh.net');
      console.error('  Verander BROKER_AUDIENCE naar mqtt-us-v1.letsmesh.net');
    }
    client.end(true);
    process.exit(1);
  });

  client.on('close', () => {
    console.log('    Verbinding gesloten.');
  });

  client.on('reconnect', () => {
    console.log('    Reconnect poging...');
  });

  client.on('offline', () => {
    console.log('    Client offline.');
  });
}

main().catch((e) => {
  console.error('Fatal:', e);
  process.exit(1);
});
