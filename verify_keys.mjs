#!/usr/bin/env node
// ============================================================================
// MeshCore Key Verificatie
// ============================================================================
// Controleert of de public key correct afgeleid is van de seed.
// Dit is CRUCIAAL — als export_private_key() een andere key geeft
// dan waarmee het device adveriseert, zal de broker altijd weigeren.
//
// Gebruik: NODE_PATH=/usr/lib/node_modules node verify_keys.mjs
// ============================================================================

import { createRequire } from 'module';
const require = createRequire(import.meta.url);

// ── Keys uit device_identity.json ──────────────────────────────────────────
const SEED = 'ab520964a364bd088359e67150da6c1d71fbd9f57cf75e392b0926cf8aff608f';

// De public key die export_private_key() teruggaf:
const EXPORTED_PUBLIC_KEY = '';  // <-- VUL IN: 64 hex chars

// De companion key die bij LetsMesh bekend is:
const COMPANION_KEY = 'D955E72CD7F64A52F85CA805AB9D7AE611A8E8D2B30D3E3F6428A5AA2AC5B0E6';
// ────────────────────────────────────────────────────────────────────────────

async function main() {
  console.log('=== MeshCore Key Verificatie ===\n');

  // Probeer de public key af te leiden van de seed via meshcore-decoder
  let derivePublicKey;
  try {
    // meshcore-decoder exporteert mogelijk crypto functies
    const decoder = require('@michaelhart/meshcore-decoder');

    // Methode 1: als er een derivePublicKey functie is
    if (decoder.derivePublicKey) {
      derivePublicKey = decoder.derivePublicKey;
    }
    // Methode 2: probeer via crypto submodule
    else if (decoder.crypto && decoder.crypto.derivePublicKey) {
      derivePublicKey = decoder.crypto.derivePublicKey;
    }

    console.log('Beschikbare exports in meshcore-decoder:');
    console.log(Object.keys(decoder).join(', '));
    console.log();
  } catch (e) {
    console.error('meshcore-decoder niet beschikbaar:', e.message);
  }

  // Alternatief: gebruik orlp-ed25519-wasm direct als het beschikbaar is
  try {
    const ed25519 = require('orlp-ed25519-wasm');
    if (ed25519) {
      console.log('orlp-ed25519-wasm exports:', Object.keys(ed25519).join(', '));

      // orlp/ed25519 key derivation:
      // De "private key" in MeshCore is eigenlijk: SHA-512(seed)[0..32] (clamped) + public_key
      // Maar de seed zelf is wat je nodig hebt om de public key af te leiden

      if (ed25519.getPublicKey || ed25519.keypairFromSeed) {
        console.log('Key derivatie functie gevonden.');
      }
    }
  } catch (e) {
    // OK, niet beschikbaar
  }

  // Handmatige verificatie: genereer een token en kijk of het lukt
  // (als createAuthToken slaagt zonder error, is het keypair consistent)
  try {
    const { createAuthToken } = require('@michaelhart/meshcore-decoder');

    if (EXPORTED_PUBLIC_KEY && EXPORTED_PUBLIC_KEY.length === 64) {
      console.log('Test 1: Token genereren met EXPORTED key...');
      const privFull = SEED + EXPORTED_PUBLIC_KEY.toLowerCase();
      try {
        const token = await createAuthToken(
          { aud: 'test', publicKey: EXPORTED_PUBLIC_KEY.toUpperCase(), iat: Math.floor(Date.now() / 1000) },
          privFull,
          EXPORTED_PUBLIC_KEY.toUpperCase()
        );
        console.log(`  ✓ Token OK met exported key: ${EXPORTED_PUBLIC_KEY.toUpperCase().substring(0, 16)}...`);
        console.log(`  Token: ${token.substring(0, 50)}...`);
      } catch (e) {
        console.log(`  ❌ MISLUKT met exported key: ${e.message}`);
      }
    } else {
      console.log('⚠️  EXPORTED_PUBLIC_KEY niet ingevuld — vul deze in uit device_identity.json');
    }

    console.log();

    // Test met companion key
    console.log('Test 2: Token genereren met COMPANION key...');
    const privComp = SEED + COMPANION_KEY.toLowerCase();
    try {
      const token = await createAuthToken(
        { aud: 'test', publicKey: COMPANION_KEY, iat: Math.floor(Date.now() / 1000) },
        privComp,
        COMPANION_KEY
      );
      console.log(`  ✓ Token OK met companion key: ${COMPANION_KEY.substring(0, 16)}...`);
      console.log(`  Token: ${token.substring(0, 50)}...`);
      console.log();
      console.log('  ⚠️  Dit zou NIET moeten lukken als de companion key');
      console.log('     een apart keypair is. Als het WEL lukt, zijn de');
      console.log('     keys op een of andere manier gerelateerd.');
    } catch (e) {
      console.log(`  ❌ Mislukt (verwacht): ${e.message}`);
      console.log('     De companion key hoort bij een ander keypair.');
    }

    console.log();
    console.log('=== Conclusie ===');
    console.log('');
    console.log('Als Test 1 slaagt → gebruik die public key voor MQTT auth');
    console.log('Als Test 1 faalt  → de seed en public key matchen niet,');
    console.log('                    je moet de correcte public key afleiden');
    console.log('                    van de seed.');

  } catch (e) {
    console.error('createAuthToken niet beschikbaar:', e.message);
  }
}

main().catch(console.error);
