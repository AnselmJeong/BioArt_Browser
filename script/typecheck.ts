import ts from 'typescript';
import { resolve, sep } from 'node:path';

// Electrobun 2 ships SDK implementation sources rather than .d.ts files.
// Check our strict code and its SDK calls; report SDK-internal diagnostics
// separately instead of weakening strictness or editing the downloaded SDK.
const configFile = ts.readConfigFile('tsconfig.json', ts.sys.readFile);
if (configFile.error) throw new Error(ts.flattenDiagnosticMessageText(configFile.error.messageText, '\n'));
const config = ts.parseJsonConfigFileContent(configFile.config, ts.sys, process.cwd());
const program = ts.createProgram(config.fileNames, config.options);
const all = [...config.errors, ...ts.getPreEmitDiagnostics(program)];
const sdkRoot = resolve('.hutch') + sep;
const own = all.filter(diagnostic => !diagnostic.file?.fileName.startsWith(sdkRoot));
if (own.length) console.error(ts.formatDiagnosticsWithColorAndContext(own, {
  getCanonicalFileName: f => f, getCurrentDirectory: ts.sys.getCurrentDirectory, getNewLine: () => '\n',
}));
console.log(`Project diagnostics: ${own.length}; upstream SDK diagnostics excluded: ${all.length - own.length}`);
process.exitCode = own.length ? 1 : 0;
