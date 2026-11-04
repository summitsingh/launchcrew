/** Summit Leather Co. starter facts for the judges workspace.
 *
 * Every claim below is stated on the company's public site
 * (https://summitleather.co, read November 2026): the homepage title,
 * meta description, and JSON-LD organization block. Nothing here is
 * invented; each fact carries its source. The judges workspace uses
 * these as its defaults instead of the fictional wallet.
 */

export type StarterFact = {
  claim: string;
  source: string;
  confirmed: boolean;
};

export const SUMMIT_LEATHER_SOURCE = 'summitleather.co';

export const SUMMIT_LEATHER_FACTS: StarterFact[] = [
  { claim: 'Summit Leather Co.', source: SUMMIT_LEATHER_SOURCE, confirmed: true },
  { claim: '100% vegan PU leather jackets', source: SUMMIT_LEATHER_SOURCE, confirmed: true },
  { claim: 'Jackets for men and women', source: SUMMIT_LEATHER_SOURCE, confirmed: true },
  { claim: 'Designed in Texas', source: SUMMIT_LEATHER_SOURCE, confirmed: true },
  { claim: 'Classic Bomber', source: SUMMIT_LEATHER_SOURCE, confirmed: true },
  { claim: 'Classic Regular Moto', source: SUMMIT_LEATHER_SOURCE, confirmed: true },
  { claim: 'Shop on Amazon', source: SUMMIT_LEATHER_SOURCE, confirmed: true },
];

export const SUMMIT_LEATHER_IDEA =
  'Summit Leather Co. launch: 100% vegan PU leather jackets, designed in Texas. Classic Bomber and Classic Regular Moto, shop on Amazon.';

export const SUMMIT_LEATHER_INSTAGRAM = 'summitleather.co';
