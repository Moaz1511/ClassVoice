import { VoiceDetailScreen } from "../../../../components/voices/VoiceDetailScreen";

type VoiceDetailRouteProps = Readonly<{
  params: Promise<{ voiceId: string }>;
}>;

export const metadata = { title: "Voice detail" };

export default async function VoiceDetailPage({ params }: VoiceDetailRouteProps) {
  const { voiceId } = await params;
  return <VoiceDetailScreen voiceId={voiceId} />;
}
