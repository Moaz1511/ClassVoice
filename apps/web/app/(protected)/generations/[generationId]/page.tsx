import { GenerationDetailScreen } from "../../../../components/generations/GenerationDetailScreen";

type GenerationDetailRouteProps = Readonly<{
  params: Promise<{ generationId: string }>;
}>;

export const metadata = { title: "Generation detail" };

export default async function GenerationDetailPage({ params }: GenerationDetailRouteProps) {
  const { generationId } = await params;
  return <GenerationDetailScreen generationId={generationId} />;
}
