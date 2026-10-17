// ============================================================================
// miniapp-visuals-route.ts — API route for Visual Artifacts gallery
// ============================================================================
//
// Place at: src/app/api/visuals/route.ts (in fosved-miniapp)
//
// Endpoints:
//   GET /api/visuals?type=...&tier=...&source_type=...&limit=...
//   GET /api/visuals/[id]  — individual artifact (separate file: src/app/api/visuals/[id]/route.ts)
//   POST /api/visuals/recall — record recall test result
//
// Auth: Telegram WebApp initData verification (use existing verifyTelegramAuth from lib/auth.ts)
// ============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();
const OWNER_ID = Number(process.env.OWNER_TELEGRAM_ID);

export async function GET(request: NextRequest) {
  // Auth check (use existing helper)
  // const auth = verifyTelegramAuth(request.headers.get('x-telegram-initdata'));
  // if (!auth) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const { searchParams } = new URL(request.url);
  const type = searchParams.get('type');
  const tier = searchParams.get('tier');
  const sourceType = searchParams.get('source_type');
  const limit = Math.min(parseInt(searchParams.get('limit') || '50'), 200);

  const where: any = { userId: OWNER_ID };
  if (type) where.type = type;
  if (tier) where.tier = parseInt(tier);
  if (sourceType) where.sourceType = sourceType;

  try {
    const artifacts = await prisma.visualArtifact.findMany({
      where,
      orderBy: { createdAt: 'desc' },
      take: limit,
      select: {
        id: true,
        type: true,
        tier: true,
        templateVersion: true,
        sourceType: true,
        sourceId: true,
        title: true,
        format: true,
        thumbnailUrl: true,
        publicUrl: true,
        recallTested: true,
        recallSuccess: true,
        publishedToChannel: true,
        createdAt: true,
        updatedAt: true
        // content NOT returned in list (too heavy)
      }
    });

    return NextResponse.json({ artifacts });
  } catch (e: any) {
    console.error('[/api/visuals]', e);
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  // For recall test recording
  // const auth = verifyTelegramAuth(request.headers.get('x-telegram-initdata'));
  // if (!auth) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  try {
    const body = await request.json();
    const { id, recallSuccess, note } = body;

    if (!id) return NextResponse.json({ error: 'Missing id' }, { status: 400 });

    const updated = await prisma.visualArtifact.update({
      where: { id: parseInt(id) },
      data: {
        recallTested: true,
        recallTestedAt: new Date(),
        recallSuccess: recallSuccess ?? null,
        recallNote: note || null
      }
    });

    return NextResponse.json({ success: true, artifact: updated });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
