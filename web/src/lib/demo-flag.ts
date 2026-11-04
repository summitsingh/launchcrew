/** Judges workspace flag (/meta-ai-hackathon-demo).
 *
 * On by default for the demo (set NEXT_PUBLIC_LAUNCHCREW_NEW_UI=false to
 * hide it). Build-time flag: the classic workspace at / is untouched and
 * always available.
 */
export const DEMO_UI_ENABLED =
  process.env.NEXT_PUBLIC_LAUNCHCREW_NEW_UI !== 'false';

export const CLASSIC_PATH = '/';
