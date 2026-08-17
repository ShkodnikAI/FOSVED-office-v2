/**
 * Seed script for OSP PostgreSQL database.
 * Creates sample Analysis + Indicator + WatchlistItem records
 * so the scheduler endpoints have data to work with.
 *
 * Usage: node scripts/seed-osp.js
 * Requires: DATABASE_URL env var pointing to PostgreSQL
 */

const { PrismaClient } = require('@prisma/client');
const prisma = new PrismaClient();

async function main() {
  console.log('Seeding OSP database...');

  // 1. Create a sample Analysis
  const analysis = await prisma.analysis.upsert({
    where: { slug: 'sample-ai-investment-2026' },
    update: {},
    create: {
      topic: 'AI Investment Landscape 2026',
      slug: 'sample-ai-investment-2026',
      depthLevel: 2,
      domain: 'finance',
      status: 'WATCHING',
      awarenessFrame: 'AI sector at inflection point — enterprise adoption accelerating',
      subject: 'AI investment trends',
      macroPhase: 'late expansion',
      eventPhase: 'inflection',
      layers: { economic: 'high', technical: 'high', political: 'medium' },
      topology: { type: 'branching', depth: 2 },
      rootCauseMap: 'Chip supply → model training cost → enterprise pricing → adoption rate',
      forcesAndPotentials: { bullish: ['enterprise demand', 'cost reduction'], bearish: ['regulation', 'talent scarcity'] },
      strategicManeuvers: { recommendation: 'long AI infrastructure' },
      twoPaths: { upside: 'AI becomes general-purpose tool', downside: 'Regulation kills commercial viability' },
      decisionTreeForecast: { probability: 0.7, direction: 'up' },
      investmentImplications: { thesis: 'Overweight AI infra, underweight AI hype' },
      verificationDate: new Date('2026-12-01'),
      overallConfidence: 'MEDIUM',
      kentProbability: 'probable (60-75%)',
      chatSummary: 'AI investment analysis — enterprise adoption accelerating, regulation risk remains',
      chatSummaryLines: 15,
      sources: [{ url: 'https://example.com', tier: 'primary' }],
      qualityGatesPassed: { gates: ['falsifiable_indicators', 'two_paths', 'confidence_calibrated'] },
    },
  });

  console.log(`  Analysis: ${analysis.id} (${analysis.topic})`);

  // 2. Create sample Indicators
  const indicators = [
    {
      description: 'GPT-5 release date announced before Q4 2026',
      verifyDate: new Date('2026-10-01'),
      isBinary: true,
      confirmsWhat: 'AI acceleration thesis — faster model releases = more enterprise adoption',
    },
    {
      description: 'EU AI Act enforcement begins affecting US companies',
      verifyDate: new Date('2026-11-15'),
      isBinary: true,
      confirmsWhat: 'Regulation downside — cross-border compliance costs increase',
    },
    {
      description: 'NVIDIA datacenter revenue grows >40% YoY in Q3 2026',
      verifyDate: new Date('2026-09-30'),
      isBinary: true,
      confirmsWhat: 'AI infrastructure demand remains strong',
    },
  ];

  for (const ind of indicators) {
    const i = await prisma.indicator.create({
      data: { analysisId: analysis.id, ...ind },
    });
    console.log(`  Indicator: ${i.id} (${i.description.slice(0, 50)}...) → verify ${i.verifyDate.toISOString().slice(0, 10)}`);
  }

  // 3. Create sample Watchlist Items
  const watchItems = [
    { topic: 'OpenAI GPT-5 announcements', frequency: 'WEEKLY' },
    { topic: 'EU AI Act enforcement timeline', frequency: 'BIWEEKLY' },
    { topic: 'NVIDIA quarterly earnings', frequency: 'WEEKLY' },
    { topic: 'AI startup funding rounds', frequency: 'DAILY' },
  ];

  for (const w of watchItems) {
    const wi = await prisma.watchlistItem.create({
      data: {
        analysisId: analysis.id,
        ...w,
        nextCheckAt: new Date(),
      },
    });
    console.log(`  Watch: ${wi.id} (${wi.topic}) [${wi.frequency}]`);
  }

  // 4. Create sample Asymmetric Bet
  const bet = await prisma.asymmetricBet.create({
    data: {
      thesis: 'NVIDIA will outperform S&P 500 by >20% in 2026',
      probability: 'probable (65%)',
      boundedDownside: 'Max 15% underperformance if AI hype collapses',
      potentialUpside: '40%+ outperformance if AI infra demand continues',
      upsideDownsideRatio: 2.7,
      exitConditions: 'Close if NVIDIA revenue growth < 20% YoY for 2 consecutive quarters',
      timeHorizon: '12 months (to Dec 2026)',
      executionMechanism: 'Long NVIDIA, short S&P 500 sector ETF',
      status: 'OPEN',
    },
  });
  console.log(`  Bet: ${bet.id} (${bet.thesis.slice(0, 50)}...)`);

  console.log('\nSeeding complete!');
}

main()
  .catch((e) => {
    console.error('Seed error:', e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
