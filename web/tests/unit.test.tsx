import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import openapiTS, { astToString, COMMENT_HEADER } from 'openapi-typescript';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import { Button } from '../src/components/ui/button';
import { cn } from '../src/lib/utils';
import { unwrap } from '../src/lib/api';

describe('frontend contract and boundaries', () => {
  it('generated client exactly matches canonical OpenAPI', async () => {
    const ast = await openapiTS(JSON.parse(readFileSync('../backend/openapi.json', 'utf8')));
    expect(COMMENT_HEADER + astToString(ast)).toBe(readFileSync('src/lib/schema.d.ts', 'utf8'));
  });
  it('never imports a Postgres driver or a backend store', () => {
    const imports: string[] = [];
    function walk(dir: string) {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, entry.name);
        if (entry.isDirectory()) { walk(path); continue; }
        if (!/\.(ts|tsx)$/.test(path)) continue;
        const source = ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true);
        function visit(node: ts.Node) {
          if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) imports.push(node.moduleSpecifier.text);
          if (ts.isCallExpression(node)) for (const arg of node.arguments) if (ts.isStringLiteral(arg)) imports.push(arg.text);
          ts.forEachChild(node, visit);
        }
        visit(source);
      }
    }
    walk('src');
    const pkg = JSON.parse(readFileSync('package.json', 'utf8'));
    imports.push(...Object.keys(pkg.dependencies));
    expect(imports.filter(i => /(^|\/)(pg|postgres|postgresql|postgres-js|prisma|knex|sequelize|typeorm|sqlalchemy)(\/|$)|backend\/store/.test(i))).toEqual([]);
  });
  it('renders disabled approval controls as native disabled buttons', () => {
    const html = renderToStaticMarkup(<Button disabled>Approve for export</Button>);
    expect(html).toContain('disabled=""');
    expect(html).toContain('Approve for export');
  });
  it('merges Tailwind utility conflicts predictably', () => {
    expect(cn('px-2', false, 'px-4')).toBe('px-4');
  });
  it('proxies API calls through the baked API_URL rewrite', () => {
    const config = readFileSync('next.config.ts', 'utf8');
    expect(config).toContain('process.env.API_URL');
    expect(config).toContain('/api/:path*');
  });
  it('rejects failed API results without exposing server details', async () => {
    await expect(unwrap(Promise.resolve({ error: { private: 'hidden' }, response: new Response('', { status: 422 }) }))).rejects.toThrow('Request failed (422). Check the API and try again.');
  });
  it('returns typed API results', async () => {
    await expect(unwrap(Promise.resolve({ data: { status: 'ok' }, response: new Response() }))).resolves.toEqual({ status: 'ok' });
  });
});
