import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const standaloneRoot = join(appRoot, ".next", "standalone", "apps", "web");
const staticSource = join(appRoot, ".next", "static");
const staticTarget = join(standaloneRoot, ".next", "static");

mkdirSync(staticTarget, { recursive: true });
cpSync(staticSource, staticTarget, { recursive: true, force: true });

const publicSource = join(appRoot, "public");
if (existsSync(publicSource)) cpSync(publicSource, join(standaloneRoot, "public"), { recursive: true, force: true });
