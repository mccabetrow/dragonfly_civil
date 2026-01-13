#!/usr/bin/env node
/**
 * Dragonfly Dashboard - Build-Time Security Scanner
 * 
 * This script runs BEFORE the Vite build to prevent secrets from being
 * exposed in the browser bundle. It scans:
 * 
 * 1. .env* files for forbidden patterns (service_role, private keys)
 * 2. Source files for accidental secret exposure via VITE_* prefix
 * 3. High-entropy strings that look like API keys or tokens
 * 
 * Exit codes:
 *   0 - All checks passed
 *   1 - Forbidden pattern detected (build MUST fail)
 *   2 - Script error
 * 
 * Usage:
 *   node scripts/security-scan.mjs
 *   npm run security:scan
 */

import { readFileSync, readdirSync, existsSync, statSync } from 'fs';
import { join, relative } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = join(__dirname, '..');

// ═══════════════════════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════════════════════

/**
 * FORBIDDEN patterns - if found, build MUST fail.
 * These should NEVER appear in frontend code or be exposed via VITE_* prefix.
 * 
 * Note: We use 'sourceOnly' flag to only check patterns in .env files (not source code)
 * for patterns that commonly appear in validation/warning code.
 */
const FORBIDDEN_PATTERNS = [
  // Service role keys - only check in .env files, not source code (where they appear in validation warnings)
  { 
    pattern: /service_role/i, 
    reason: 'Service role key detected - this grants full DB access',
    envOnly: true,  // Only check in .env files, not source code
  },
  { 
    pattern: /SUPABASE_SERVICE_ROLE/i, 
    reason: 'Service role key reference detected',
    envOnly: true,
  },
  
  // Actual secret VALUE patterns (these indicate real secrets, not references)
  { pattern: /sk-[a-zA-Z0-9]{20,}/g, reason: 'OpenAI API key pattern detected (sk-...)' },
  { pattern: /AKIA[0-9A-Z]{16}/g, reason: 'AWS Access Key ID pattern detected (AKIA...)' },
  { pattern: /-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----/i, reason: 'Private key detected' },
  { pattern: /-----BEGIN CERTIFICATE-----/i, reason: 'Certificate detected' },
  { pattern: /postgres(ql)?:\/\/[^:]+:[^@]+@/i, reason: 'Database connection string with password detected' },
  { pattern: /mysql:\/\/[^:]+:[^@]+@/i, reason: 'MySQL connection string with password detected' },
  
  // Generic secret patterns in VITE_ variable DEFINITIONS (assignment context)
  { 
    pattern: /VITE_[A-Z_]*SECRET\s*=/i, 
    reason: 'VITE_ variable containing "SECRET" - secrets must not be exposed to browser',
  },
  { 
    pattern: /VITE_[A-Z_]*PASSWORD\s*=/i, 
    reason: 'VITE_ variable containing "PASSWORD" - passwords must not be exposed',
  },
  { 
    pattern: /VITE_[A-Z_]*PRIVATE\s*=/i, 
    reason: 'VITE_ variable containing "PRIVATE" - private values must not be exposed',
  },
  { 
    pattern: /VITE_[A-Z_]*SERVICE_ROLE\s*=/i, 
    reason: 'VITE_ variable with service_role - this grants admin access',
  },
  
  // JWT tokens (except anon keys which are safe)
  { 
    pattern: /eyJ[a-zA-Z0-9_-]{30,}\.eyJ[a-zA-Z0-9_-]{30,}\.[a-zA-Z0-9_-]{30,}/g, 
    reason: 'JWT token detected - verify this is an anon key, not service_role',
    // Allow if it's explicitly the anon key variable
    allowIn: ['VITE_SUPABASE_ANON_KEY', '.env.example'],
  },
];

/**
 * Source-only patterns - check in source files for dangerous IMPORTS of env vars
 */
const SOURCE_FORBIDDEN_PATTERNS = [
  // Importing/accessing non-VITE_ env vars in frontend (won't work and indicates confusion)
  { 
    pattern: /process\.env\./i, 
    reason: 'process.env is not available in Vite browser builds - use import.meta.env instead',
  },
  // Accessing server-only env vars
  { 
    pattern: /import\.meta\.env\.SUPABASE_SERVICE_ROLE/i, 
    reason: 'Attempting to access service_role key in frontend code',
  },
  { 
    pattern: /import\.meta\.env\.OPENAI_API_KEY/i, 
    reason: 'Attempting to access OpenAI API key in frontend code',
  },
  {
    pattern: /from\s+['"]openai['"]/i,
    reason: 'OpenAI SDK import detected - move AI calls to the backend',
  },
  {
    pattern: /import\s+openai\b/i,
    reason: 'OpenAI SDK import detected - this package is forbidden in browser bundles',
  },
  {
    pattern: /require\(\s*['"]openai['"]\s*\)/i,
    reason: 'OpenAI SDK require() detected - remove server-only dependencies from frontend',
  },
  {
    pattern: /import\(\s*['"]openai['"]\s*\)/i,
    reason: 'Dynamic OpenAI SDK import detected - this leaks API usage to the client',
  },
];

/**
 * WARNING patterns - log a warning but don't fail the build.
 * These are suspicious but may have legitimate uses.
 */
const WARNING_PATTERNS = [
  { pattern: /VITE_.*KEY/i, reason: 'VITE_ variable ending in KEY - verify this is a public/anon key only' },
  { pattern: /VITE_.*TOKEN/i, reason: 'VITE_ variable containing TOKEN - verify this is safe to expose' },
];

/**
 * ALLOWED VITE_ variables - these are safe to expose to the browser.
 */
const ALLOWED_VITE_VARS = [
  'VITE_API_BASE_URL',        // Public API endpoint URL
  'VITE_SUPABASE_URL',        // Supabase project URL (public)
  'VITE_SUPABASE_ANON_KEY',   // Supabase anon key (public, RLS-protected)
  'VITE_DRAGONFLY_API_KEY',   // API key for backend auth (meant for browser)
  'VITE_DEMO_MODE',           // Demo mode flag
  'VITE_IS_DEMO',             // Deprecated demo flag
  'VITE_DASHBOARD_SOURCE',    // Data source selector
  'VITE_DEBUG',               // Debug mode flag
  'VITE_LOG_LEVEL',           // Logging level
  'VITE_MOCK_MODE',           // Mock mode for testing
];

const ALLOWED_VITE_VAR_SET = new Set(ALLOWED_VITE_VARS);

const FORBIDDEN_VITE_KEYWORDS = [
  'SECRET',
  'KEY',
  'TOKEN',
  'PASSWORD',
  'OPENAI',
  'SERVICE_ROLE',
];

/**
 * File extensions to scan in src/
 */
const SOURCE_EXTENSIONS = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'];

/**
 * Files to skip entirely (node_modules is already skipped)
 */
const SKIP_PATTERNS = [
  /node_modules/,
  /\.git/,
  /dist/,
  /\.cache/,
  /coverage/,
];

const violations = [];
const warnings = [];

function isAllowedViteVar(key) {
  return ALLOWED_VITE_VAR_SET.has(key);
}

function containsForbiddenKeyword(key) {
  if (!key) return false;
  const upper = key.toUpperCase();
  return FORBIDDEN_VITE_KEYWORDS.some(keyword => upper.includes(keyword));
}

function ensureAnonKeyIsAnon(value, context) {
  if (!value) return;

  try {
    const parts = value.split('.');
    if (parts.length !== 3) return;

    const payload = Buffer.from(parts[1], 'base64').toString('utf8');
    if (payload.includes('service_role')) {
      violations.push({
        file: context.file,
        line: context.line,
        match: context.match,
        reason: 'VITE_SUPABASE_ANON_KEY is a service_role JWT! Use the anon/public key instead.',
      });
    }
  } catch {
    // Ignore decode failures
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// UTILITY FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Calculate Shannon entropy of a string (higher = more random = more likely a secret)
 */
function calculateEntropy(str) {
  if (!str || str.length === 0) return 0;
  
  const freq = {};
  for (const char of str) {
    freq[char] = (freq[char] || 0) + 1;
  }
  
  let entropy = 0;
  const len = str.length;
  for (const count of Object.values(freq)) {
    const p = count / len;
    entropy -= p * Math.log2(p);
  }
  
  return entropy;
}

/**
 * Check if a string looks like a high-entropy secret.
 * Returns true if the string appears to be a random secret/token.
 */
function isHighEntropySecret(value) {
  if (!value || value.length < 20) return false;
  
  // Skip URLs, paths, and common non-secret patterns
  if (value.match(/^https?:\/\//i)) return false;
  if (value.match(/^\/[a-z]/i)) return false;
  if (value.includes(' ')) return false;
  
  // Check entropy - secrets typically have entropy > 4.0
  const entropy = calculateEntropy(value);
  
  // Also check for base64-like patterns (high ratio of alphanumeric)
  const alphanumRatio = (value.match(/[a-zA-Z0-9]/g) || []).length / value.length;
  
  return entropy > 4.0 && alphanumRatio > 0.8 && value.length >= 24;
}

/**
 * Recursively get all files in a directory
 */
function getAllFiles(dir, extensions = null) {
  const files = [];
  
  if (!existsSync(dir)) return files;
  
  const entries = readdirSync(dir, { withFileTypes: true });
  
  for (const entry of entries) {
    const fullPath = join(dir, entry.name);
    
    // Skip patterns
    if (SKIP_PATTERNS.some(p => p.test(fullPath))) continue;
    
    if (entry.isDirectory()) {
      files.push(...getAllFiles(fullPath, extensions));
    } else if (entry.isFile()) {
      if (!extensions || extensions.some(ext => entry.name.endsWith(ext))) {
        files.push(fullPath);
      }
    }
  }
  
  return files;
}

/**
 * Get all .env* files in the root directory
 */
function getEnvFiles() {
  const entries = readdirSync(ROOT);
  return entries
    .filter(name => name.startsWith('.env'))
    .map(name => join(ROOT, name));
}

// ═══════════════════════════════════════════════════════════════════════════
// SCANNING FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Scan a file for forbidden patterns
 */
function scanFile(filePath, content) {
  const relPath = relative(ROOT, filePath);
  const lines = content.split('\n');
  
  for (let lineNum = 0; lineNum < lines.length; lineNum++) {
    const line = lines[lineNum];
    
    // Skip comments
    if (line.trim().startsWith('#') || line.trim().startsWith('//')) continue;
    
    // Check forbidden patterns (skip envOnly patterns for source files)
    for (const { pattern, reason, allowIn, envOnly } of FORBIDDEN_PATTERNS) {
      // Skip envOnly patterns when scanning source files
      if (envOnly) continue;
      
      // Check if this file/context is allowed
      if (allowIn && allowIn.some(allowed => relPath.includes(allowed) || line.includes(allowed))) {
        continue;
      }
      
      const match = line.match(pattern);
      if (match) {
        violations.push({
          file: relPath,
          line: lineNum + 1,
          match: match[0].substring(0, 50) + (match[0].length > 50 ? '...' : ''),
          reason,
        });
      }
    }
    
    // Check source-specific forbidden patterns
    for (const { pattern, reason } of SOURCE_FORBIDDEN_PATTERNS) {
      const match = line.match(pattern);
      if (match) {
        violations.push({
          file: relPath,
          line: lineNum + 1,
          match: match[0].substring(0, 50) + (match[0].length > 50 ? '...' : ''),
          reason,
        });
      }
    }
    
    // Check warning patterns
    for (const { pattern, reason } of WARNING_PATTERNS) {
      const match = line.match(pattern);
      if (match) {
        // Only warn if it's not an allowed variable
        const isAllowed = ALLOWED_VITE_VARS.some(v => line.includes(v));
        if (!isAllowed) {
          warnings.push({
            file: relPath,
            line: lineNum + 1,
            match: match[0],
            reason,
          });
        }
      }
    }
  }
}

/**
 * Scan .env files for forbidden values
 */
function scanEnvFile(filePath) {
  const relPath = relative(ROOT, filePath);
  const content = readFileSync(filePath, 'utf8');
  const lines = content.split('\n');
  
  for (let lineNum = 0; lineNum < lines.length; lineNum++) {
    const line = lines[lineNum].trim();
    
    // Skip comments and empty lines
    if (!line || line.startsWith('#')) continue;
    
    // Parse KEY=VALUE
    const eqIndex = line.indexOf('=');
    if (eqIndex === -1) continue;
    
    const key = line.substring(0, eqIndex).trim();
    const value = line.substring(eqIndex + 1).trim();
    
    // Skip empty values
    if (!value) continue;
    
    // Check for forbidden keys that should never be in VITE_ prefix
    if (key.startsWith('VITE_')) {
      const allowedVar = isAllowedViteVar(key);
      const hasKeyword = containsForbiddenKeyword(key);

      if (!allowedVar && hasKeyword) {
        violations.push({
          file: relPath,
          line: lineNum + 1,
          match: key,
          reason: `Forbidden VITE_ variable: ${key} contains sensitive keyword and will be exposed to the browser`,
        });
      } else if (!allowedVar) {
        warnings.push({
          file: relPath,
          line: lineNum + 1,
          match: key,
          reason: `Unknown VITE_ variable: ${key} - add to ALLOWED_VITE_VARS if intentional`,
        });
      }

      if (key === 'VITE_SUPABASE_ANON_KEY') {
        ensureAnonKeyIsAnon(value, {
          file: relPath,
          line: lineNum + 1,
          match: `${key}=<jwt-with-service_role>`,
        });
      }
    }
    
    // Check for high-entropy secrets in any VITE_ variable value
    if (key.startsWith('VITE_') && isHighEntropySecret(value)) {
      // This is okay for anon keys, but warn for others
      if (key !== 'VITE_SUPABASE_ANON_KEY' && key !== 'VITE_DRAGONFLY_API_KEY') {
        warnings.push({
          file: relPath,
          line: lineNum + 1,
          match: `${key}=<high-entropy-value>`,
          reason: 'High-entropy value in VITE_ variable - verify this is meant to be public',
        });
      }
    }
    
    // Check forbidden patterns in values
    for (const { pattern, reason, allowIn } of FORBIDDEN_PATTERNS) {
      // Skip JWT check for anon key
      if (allowIn && allowIn.includes('VITE_SUPABASE_ANON_KEY') && key === 'VITE_SUPABASE_ANON_KEY') {
        continue;
      }
      
      if (pattern.test(value)) {
        violations.push({
          file: relPath,
          line: lineNum + 1,
          match: `${key}=<redacted>`,
          reason,
        });
      }
    }
  }
}

/**
 * Scan source files for accidental secret exposure
 */
function scanSourceFiles() {
  const srcDir = join(ROOT, 'src');
  const files = getAllFiles(srcDir, SOURCE_EXTENSIONS);
  
  for (const filePath of files) {
    try {
      const content = readFileSync(filePath, 'utf8');
      scanFile(filePath, content);
    } catch (err) {
      console.error(`⚠️  Could not read file: ${relative(ROOT, filePath)}`);
    }
  }
}

/**
 * Check required environment variables for production
 */
function checkRequiredEnvVars() {
  const isCI = process.env.CI === 'true' || process.env.VERCEL === '1';
  
  if (isCI) {
    const required = ['VITE_API_BASE_URL', 'VITE_SUPABASE_URL', 'VITE_SUPABASE_ANON_KEY'];
    const missing = required.filter(key => !process.env[key]);
    
    if (missing.length > 0) {
      violations.push({
        file: 'environment',
        line: 0,
        match: missing.join(', '),
        reason: `Missing required environment variables for production build: ${missing.join(', ')}`,
      });
    }
  }
}

function checkRuntimeViteVars() {
  const runtimeVars = Object.entries(process.env).filter(([key]) => key.startsWith('VITE_'));
  
  for (const [key, rawValue] of runtimeVars) {
    const value = typeof rawValue === 'string' ? rawValue : '';
    const allowedVar = isAllowedViteVar(key);
    const hasKeyword = containsForbiddenKeyword(key);
    
    if (!allowedVar && hasKeyword) {
      violations.push({
        file: 'environment',
        line: 0,
        match: `${key}=<runtime>`,
        reason: `Forbidden runtime VITE_ variable detected: ${key} contains sensitive keyword`,
      });
    }
    
    if (key === 'VITE_SUPABASE_ANON_KEY') {
      ensureAnonKeyIsAnon(value, {
        file: 'environment',
        line: 0,
        match: 'process.env.VITE_SUPABASE_ANON_KEY',
      });
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// MAIN
// ═══════════════════════════════════════════════════════════════════════════

console.log('');
console.log('═══════════════════════════════════════════════════════════════════════════');
console.log('  🔒 Dragonfly Security Scanner - Build-Time Secret Detection');
console.log('═══════════════════════════════════════════════════════════════════════════');
console.log('');

// 1. Scan .env files
console.log('📁 Scanning .env files...');
const envFiles = getEnvFiles();
for (const filePath of envFiles) {
  // Skip .env.example
  if (filePath.endsWith('.env.example')) continue;
  
  try {
    scanEnvFile(filePath);
    console.log(`   ✓ ${relative(ROOT, filePath)}`);
  } catch (err) {
    console.error(`   ⚠️ Could not read: ${relative(ROOT, filePath)}`);
  }
}

// 2. Scan source files
console.log('');
console.log('📁 Scanning source files...');
scanSourceFiles();
console.log(`   ✓ Scanned ${getAllFiles(join(ROOT, 'src'), SOURCE_EXTENSIONS).length} files`);

// 3. Check required env vars in CI
console.log('');
console.log('🔍 Checking environment configuration...');
checkRequiredEnvVars();
console.log('   ✓ Environment check complete');

console.log('');
console.log('🛡️  Inspecting runtime VITE_* variables...');
checkRuntimeViteVars();
console.log('   ✓ Runtime VITE_* scan complete');

// 4. Report results
console.log('');
console.log('═══════════════════════════════════════════════════════════════════════════');

if (warnings.length > 0) {
  console.log('');
  console.log(`⚠️  WARNINGS (${warnings.length}):`);
  console.log('');
  for (const w of warnings) {
    console.log(`   ${w.file}:${w.line}`);
    console.log(`      Match: ${w.match}`);
    console.log(`      Reason: ${w.reason}`);
    console.log('');
  }
}

if (violations.length > 0) {
  console.log('');
  console.log(`❌ SECURITY VIOLATIONS (${violations.length}):`);
  console.log('');
  for (const v of violations) {
    console.log(`   ${v.file}:${v.line}`);
    console.log(`      Match: ${v.match}`);
    console.log(`      Reason: ${v.reason}`);
    console.log('');
  }
  console.log('═══════════════════════════════════════════════════════════════════════════');
  console.log('');
  console.log('❌ BUILD BLOCKED: Fix the security violations above before deploying.');
  console.log('');
  console.log('   If a pattern is a false positive, add it to ALLOWED_VITE_VARS in');
  console.log('   scripts/security-scan.mjs');
  console.log('');
  process.exit(1);
} else {
  console.log('');
  console.log('✅ SECURITY SCAN PASSED');
  console.log('');
  console.log('   No forbidden patterns detected. Build may proceed.');
  console.log('');
  process.exit(0);
}
