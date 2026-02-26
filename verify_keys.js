#!/usr/bin/env node
// ============================================================================
// MeshCore Key Verificatie
// ============================================================================
// Leest ~/.meshcore-gui/device_identity.json automatisch.
// Controleert of seed + public key een geldig keypair vormen.
//
// Gebruik: NODE_PATH=/usr/lib/node_modules node verify_keys.js
// ============================================================================

const fs = require('fs');
const path = require('path');
const os = require('os');

// ── Identity file laden ─────────────────────────────────────────────────────
const IDENTITY_PATH = path.join(os.homedir(), '.meshcore-gui', 'device_identity.json');

// Companion key (bekend bij LetsMesh)
const COMPANION_KEY = 'D955E72CD7F64A52F85CA805AB9D7AE611A8E8D2B30D3E3F6428A5AA2AC5B0E6';

var identity;
try {
  var raw = fs.readFileSync(IDENTITY_PATH, 'utf8');
  identity = JSON.parse(raw);
} catch (e) {
  console.error('❌ Kan ' + IDENTITY_PATH + ' niet lezen: ' + e.message);
  process.exit(1);
}

var seed    = (identity.private_key || '').toLowerCase().trim();
var pubKey  = (identity.public_key  || '').toUpperCase().trim();
var devName = identity.device_name  || 'onbekend';

async function main() {
  console.log('=== MeshCore Key Verificatie ===\n');
  console.log('Device:         ' + devName);
  console.log('Identity file:  ' + IDENTITY_PATH);
  console.log('');
  console.log('Device seed:    ' + seed.substring(0, 16) + '...');
  console.log('Device pub:     ' + pubKey.substring(0, 16) + '...');
  console.log('Companion pub:  ' + COMPANION_KEY.substring(0, 16) + '...');
  console.log('');

  // ── meshcore-decoder laden ──────────────────────────────────────────────
  var createAuthToken;
  try {
    var decoder = require('@michaelhart/meshcore-decoder');
    createAuthToken = decoder.createAuthToken;
    console.log('meshcore-decoder geladen ✓');
    console.log('Exports: ' + Object.keys(decoder).join(', '));
    console.log('');
  } catch (e) {
    console.error('❌ meshcore-decoder niet beschikbaar: ' + e.message);
    console.error('   NODE_PATH=/usr/lib/node_modules node verify_keys.js');
    process.exit(1);
  }

  // ── Test 1: Device key (seed + exported pub) ────────────────────────────
  console.log('--- Test 1: Device keypair (seed + exported public key) ---');
  if (seed.length === 64 && pubKey.length === 64) {
    var privFull = seed + pubKey.toLowerCase();
    try {
      var token = await createAuthToken(
        { aud: 'test', publicKey: pubKey, iat: Math.floor(Date.now() / 1000) },
        privFull,
        pubKey
      );
      console.log('✅ Token OK — device keypair is geldig');
      console.log('   Public key voor MQTT: ' + pubKey);
      console.log('   Username: v1_' + pubKey);
      console.log('');
    } catch (e) {
      console.log('❌ MISLUKT: ' + e.message);
      console.log('   De seed en public key matchen NIET.');
      console.log('   export_private_key() geeft mogelijk een verkeerde combinatie.');
      console.log('');
    }
  } else {
    console.log('⚠️  Overgeslagen — seed (' + seed.length + ' chars) of pub (' + pubKey.length + ' chars) onjuiste lengte');
    console.log('');
  }

  // ── Test 2: Companion key (seed + companion pub) ────────────────────────
  console.log('--- Test 2: Seed + companion key (verwacht: MISLUKT) ---');
  var privComp = seed + COMPANION_KEY.toLowerCase();
  try {
    var token2 = await createAuthToken(
      { aud: 'test', publicKey: COMPANION_KEY, iat: Math.floor(Date.now() / 1000) },
      privComp,
      COMPANION_KEY
    );
    console.log('⚠️  Token OK — onverwacht! Seed hoort blijkbaar bij companion key.');
    console.log('   Dit zou betekenen dat de companion key de juiste is voor MQTT.');
    console.log('');
  } catch (e) {
    console.log('✓  Mislukt (verwacht): companion key hoort bij een ander keypair.');
    console.log('');
  }

  // ── Test 3: Check of de seed überhaupt 64 hex chars is ─────────────────
  console.log('--- Test 3: Raw identity dump ---');
  console.log(JSON.stringify(identity, null, 2));
}

main().catch(function (e) {
  console.error('Fatal: ' + e);
  process.exit(1);
});
