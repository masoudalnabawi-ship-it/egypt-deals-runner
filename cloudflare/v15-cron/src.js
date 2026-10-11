const REPO = 'masoudalnabawi-ship-it/egypt-deals-runner';
const REF = 'amazon-v15-rebuild';
const WORKFLOW = 'v15-live-probe.yml';

export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil((async () => {
      if (!env.V15_GITHUB_DISPATCH_TOKEN) throw new Error('V15_GITHUB_DISPATCH_TOKEN missing');
      const response = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${env.V15_GITHUB_DISPATCH_TOKEN}`,
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'User-Agent': 'egypt-amazon-v15-cron'
        },
        body: JSON.stringify({ ref: REF })
      });
      if (response.status !== 204) {
        const body = (await response.text()).slice(0, 300);
        console.error(`V15_DISPATCH_FAILED ${response.status} ${body}`);
        throw new Error(`V15_DISPATCH_FAILED ${response.status}`);
      }
      console.log('V15_DISPATCH_ACCEPTED');
    })());
  },
  async fetch() { return new Response('Amazon V15 cron active', {status: 200}); }
};
