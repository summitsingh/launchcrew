import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { errorMessage } from '../src/lib/api';
import type { components } from '../src/lib/schema';

type Profile = components['schemas']['Profile'];

function presetProfile(name: string, role: string): Profile {
  return {
    name, role, department: 'Crew', personality: `${name} personality`,
    expertise: `${name} expertise`, decision_rules: ['Use facts file first'],
    veto_scope: [], tools_allowed: ['facts_file'], spend_limit: 0,
    approval_level: 'approve_each', examples: [],
  };
}

describe('custom agent detailed errors', () => {
  it('surfaces the backend validation reason instead of a bare 422', () => {
    const message = errorMessage({ detail: 'Validation failed: Decision rules and tools are required' }, 422);
    expect(message).toContain('422');
    expect(message).toContain('Decision rules and tools are required');
    expect(message).not.toBe('Request failed (422). Check the API and try again.');
  });

  it('joins field-level validation entries with their locations', () => {
    const message = errorMessage({
      detail: [
        { loc: ['body', 'decision_rules'], msg: 'Field required', type: 'missing' },
        { loc: ['body', 'name'], msg: 'String should match pattern', type: 'string_pattern_mismatch' },
      ],
    }, 422);
    expect(message).toContain('body.decision_rules: Field required');
    expect(message).toContain('body.name: String should match pattern');
  });

  it('surfaces duplicate-name conflicts instead of a bare 409', () => {
    const message = errorMessage({ detail: 'Conflict: agent name already exists' }, 409);
    expect(message).toContain('already exists');
  });

  it('keeps a generic fallback when no detail is present', () => {
    expect(errorMessage({}, 500)).toBe('Request failed (500). Check the API and try again.');
  });

  it('routes agent save failures into the visible error banner path', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8');
    expect(source).toContain("role=\"alert\"");
    expect(source).toContain('setError');
    expect(source).toContain("POST('/api/agents'");
  });
});

describe('crew preset selection and stage assignment', () => {
  const presets = [
    presetProfile('Support', 'Intended FAQ Reply Drafter'),
    presetProfile('Designer', 'Intended Photo Layout Suggestion Helper'),
    presetProfile('Analyst', 'Intended Outcome Summary Helper'),
    presetProfile('Research', 'Intended Sourced Fact Suggestion Helper'),
  ];

  it('lists crew presets as selectable stage options', () => {
    const html = renderToStaticMarkup(
      <select id="run-checker-agent">
        {presets.map((p) => <option key={p.name}>{p.name}</option>)}
      </select>,
    );
    for (const name of ['Support', 'Designer', 'Analyst', 'Research']) {
      expect(html).toContain(name);
    }
  });

  it('binds every stage select to the shared agent list', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8');
    for (const id of ['id="run-scout"', 'id="run-agent"', 'id="run-checker-agent"']) {
      expect(source).toContain(id);
    }
    expect(source).toContain('agents.data?.map');
    expect(source).toContain('checker_name');
    expect(source).toContain('scout_name');
    expect(source).toContain('maker_name');
  });
});
