import { GenerationDetailScreen } from "../../../../components/generations/GenerationDetailScreen";

type GenerationDetailRouteProps = Readonly<{
  params: Promise<{ generationId: string }>;
}>;

export const metadata = { title: "Generation detail" };

export default async function GenerationDetailPage({ params }: GenerationDetailRouteProps) {
  const { generationId } = await params;
  const useSyntheticFixture = process.env.CLASSVOICE_E2E_FIXTURES === "1" && generationId === "synthetic-succeeded";
  return <GenerationDetailScreen generationId={generationId} initialStatus={useSyntheticFixture ? "succeeded" : undefined} audioSrc={useSyntheticFixture ? "/e2e-fixtures/audio" : undefined} captionsSrc={useSyntheticFixture ? "/e2e-fixtures/captions" : undefined} />;
}
