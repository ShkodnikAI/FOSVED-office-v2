-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "public";

-- CreateEnum
CREATE TYPE "AnalysisStatus" AS ENUM ('DRAFTED', 'PUBLISHED', 'WATCHING', 'VERIFIED', 'MISSED', 'PARTIAL', 'SUPERSEDED');

-- CreateEnum
CREATE TYPE "ConfidenceLevel" AS ENUM ('LOW', 'MEDIUM', 'HIGH');

-- CreateEnum
CREATE TYPE "WatchFrequency" AS ENUM ('DAILY', 'WEEKLY', 'BIWEEKLY');

-- CreateEnum
CREATE TYPE "BetStatus" AS ENUM ('OPEN', 'WATCHING', 'CLOSED_PROFIT', 'CLOSED_LOSS', 'CLOSED_NEUTRAL', 'SUPERSEDED');

-- CreateTable
CREATE TABLE "Analysis" (
    "id" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "topic" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "depthLevel" INTEGER NOT NULL,
    "domain" TEXT NOT NULL,
    "status" "AnalysisStatus" NOT NULL DEFAULT 'DRAFTED',
    "publishedAt" TIMESTAMP(3),
    "verifiedAt" TIMESTAMP(3),
    "supersededById" TEXT,
    "awarenessFrame" TEXT NOT NULL,
    "subject" TEXT NOT NULL,
    "macroPhase" TEXT NOT NULL,
    "eventPhase" TEXT NOT NULL,
    "layers" JSONB NOT NULL,
    "topology" JSONB NOT NULL,
    "rootCauseMap" TEXT NOT NULL,
    "forcesAndPotentials" JSONB NOT NULL,
    "strategicManeuvers" JSONB NOT NULL,
    "twoPaths" JSONB NOT NULL,
    "systemHealth" JSONB,
    "decisionTreeForecast" JSONB NOT NULL,
    "investmentImplications" JSONB NOT NULL,
    "verificationDate" TIMESTAMP(3) NOT NULL,
    "brierScore" DOUBLE PRECISION,
    "actualOutcome" TEXT,
    "errorCategory" TEXT,
    "overallConfidence" "ConfidenceLevel" NOT NULL,
    "kentProbability" TEXT,
    "chatSummary" TEXT NOT NULL,
    "chatSummaryLines" INTEGER NOT NULL,
    "sources" JSONB NOT NULL,
    "newsContextUsed" BOOLEAN NOT NULL DEFAULT false,
    "modelUsed" TEXT,
    "providerUsed" TEXT,
    "tokenBudgetUsed" INTEGER,
    "durationSeconds" INTEGER,
    "autoEscalationTriggers" JSONB,
    "qualityGatesPassed" JSONB NOT NULL,
    "qualityGatesFailed" JSONB,

    CONSTRAINT "Analysis_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Indicator" (
    "id" TEXT NOT NULL,
    "analysisId" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "verifyDate" TIMESTAMP(3) NOT NULL,
    "isBinary" BOOLEAN NOT NULL DEFAULT true,
    "result" BOOLEAN,
    "verifiedAt" TIMESTAMP(3),
    "confirmsWhat" TEXT NOT NULL,
    "preVerifyReminderSent" BOOLEAN NOT NULL DEFAULT false,
    "scheduledJobId" TEXT,

    CONSTRAINT "Indicator_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "WatchlistItem" (
    "id" TEXT NOT NULL,
    "analysisId" TEXT NOT NULL,
    "topic" TEXT NOT NULL,
    "frequency" "WatchFrequency" NOT NULL DEFAULT 'DAILY',
    "lastCheckAt" TIMESTAMP(3),
    "nextCheckAt" TIMESTAMP(3),
    "active" BOOLEAN NOT NULL DEFAULT true,
    "lastDelta" TEXT,
    "deltaCount" INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT "WatchlistItem_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "BrierScoreLog" (
    "id" TEXT NOT NULL,
    "analysisId" TEXT NOT NULL,
    "date" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "forecastProbability" DOUBLE PRECISION NOT NULL,
    "actualOutcome" DOUBLE PRECISION NOT NULL,
    "brierScore" DOUBLE PRECISION NOT NULL,
    "cumulativeBrier" DOUBLE PRECISION NOT NULL,
    "totalForecasts" INTEGER NOT NULL,

    CONSTRAINT "BrierScoreLog_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CalibrationCurvePoint" (
    "id" TEXT NOT NULL,
    "date" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "binLabel" TEXT NOT NULL,
    "binCenter" DOUBLE PRECISION NOT NULL,
    "forecastsInBin" INTEGER NOT NULL,
    "actualRate" DOUBLE PRECISION NOT NULL,
    "deviation" DOUBLE PRECISION NOT NULL,

    CONSTRAINT "CalibrationCurvePoint_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AsymmetricBet" (
    "id" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "thesis" TEXT NOT NULL,
    "probability" TEXT NOT NULL,
    "boundedDownside" TEXT NOT NULL,
    "potentialUpside" TEXT NOT NULL,
    "upsideDownsideRatio" DOUBLE PRECISION,
    "exitConditions" TEXT NOT NULL,
    "timeHorizon" TEXT NOT NULL,
    "executionMechanism" TEXT NOT NULL,
    "status" "BetStatus" NOT NULL DEFAULT 'OPEN',
    "closedAt" TIMESTAMP(3),
    "resultPnl" DOUBLE PRECISION,

    CONSTRAINT "AsymmetricBet_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "Analysis_slug_key" ON "Analysis"("slug");

-- CreateIndex
CREATE INDEX "Analysis_topic_idx" ON "Analysis"("topic");

-- CreateIndex
CREATE INDEX "Analysis_status_idx" ON "Analysis"("status");

-- CreateIndex
CREATE INDEX "Analysis_domain_idx" ON "Analysis"("domain");

-- CreateIndex
CREATE INDEX "Analysis_verificationDate_idx" ON "Analysis"("verificationDate");

-- CreateIndex
CREATE INDEX "Analysis_createdAt_idx" ON "Analysis"("createdAt");

-- CreateIndex
CREATE INDEX "Indicator_verifyDate_idx" ON "Indicator"("verifyDate");

-- CreateIndex
CREATE INDEX "Indicator_analysisId_idx" ON "Indicator"("analysisId");

-- CreateIndex
CREATE INDEX "WatchlistItem_nextCheckAt_idx" ON "WatchlistItem"("nextCheckAt");

-- CreateIndex
CREATE INDEX "WatchlistItem_active_idx" ON "WatchlistItem"("active");

-- CreateIndex
CREATE INDEX "BrierScoreLog_analysisId_idx" ON "BrierScoreLog"("analysisId");

-- CreateIndex
CREATE INDEX "BrierScoreLog_date_idx" ON "BrierScoreLog"("date");

-- CreateIndex
CREATE INDEX "CalibrationCurvePoint_date_idx" ON "CalibrationCurvePoint"("date");

-- CreateIndex
CREATE INDEX "AsymmetricBet_status_idx" ON "AsymmetricBet"("status");

-- CreateIndex
CREATE INDEX "AsymmetricBet_createdAt_idx" ON "AsymmetricBet"("createdAt");

-- AddForeignKey
ALTER TABLE "Analysis" ADD CONSTRAINT "Analysis_supersededById_fkey" FOREIGN KEY ("supersededById") REFERENCES "Analysis"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Indicator" ADD CONSTRAINT "Indicator_analysisId_fkey" FOREIGN KEY ("analysisId") REFERENCES "Analysis"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "WatchlistItem" ADD CONSTRAINT "WatchlistItem_analysisId_fkey" FOREIGN KEY ("analysisId") REFERENCES "Analysis"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BrierScoreLog" ADD CONSTRAINT "BrierScoreLog_analysisId_fkey" FOREIGN KEY ("analysisId") REFERENCES "Analysis"("id") ON DELETE CASCADE ON UPDATE CASCADE;

