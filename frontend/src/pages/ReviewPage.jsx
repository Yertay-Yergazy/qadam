import { Badge, Box, Button, Card, Group, List, Select, SimpleGrid, Stack, Text, Textarea, TextInput, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconCalendarEvent, IconCheck, IconChecklist, IconPencil, IconSparkles, IconX } from "@tabler/icons-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useMe } from "../context.jsx";
import { Banner, EmptyState, Page, UserAvatar } from "../components/ui.jsx";
import { dayMonth } from "../format.js";
import { useLoad } from "../hooks.js";

const NONE = "none";

function EditForm({ draft, onSave, onCancel, busy }) {
  const { activeUsers } = useMe();
  const [f, setF] = useState({
    title: draft.title,
    description: draft.description,
    criteria: draft.acceptance_criteria.join("\n"),
    assignee_id: draft.assignee_id ? String(draft.assignee_id) : NONE,
    due_text: draft.due_text ?? "",
  });
  const set = (k) => (e) => setF({ ...f, [k]: e.currentTarget.value });

  return (
    <Stack>
      <TextInput label="Название" value={f.title} onChange={set("title")} required />
      <Textarea label="Описание" autosize minRows={2} value={f.description} onChange={set("description")} />
      <Textarea label="Критерии готовности" description="По одному на строку" autosize minRows={2} value={f.criteria} onChange={set("criteria")} />
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <Select
          label="Исполнитель"
          data={[{ value: NONE, label: "Не указан" }, ...activeUsers.map((u) => ({ value: String(u.id), label: u.name }))]}
          value={f.assignee_id}
          onChange={(v) => setF({ ...f, assignee_id: v ?? NONE })}
          allowDeselect={false}
          searchable
        />
        <TextInput label="Срок" value={f.due_text} onChange={set("due_text")} placeholder="Не указан" />
      </SimpleGrid>
      <Group>
        <Button
          loading={busy}
          disabled={!f.title.trim()}
          onClick={() =>
            onSave({
              title: f.title,
              description: f.description,
              acceptance_criteria: f.criteria.split("\n"),
              assignee_id: f.assignee_id === NONE ? null : Number(f.assignee_id),
              due_text: f.due_text,
            })
          }
        >
          Сохранить
        </Button>
        <Button variant="default" onClick={onCancel}>Отмена</Button>
      </Group>
    </Stack>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
      <Box mt={4}>{children}</Box>
    </div>
  );
}

function DraftCard({ draft, onDecided }) {
  const { can, byId } = useMe();
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const assignee = draft.assignee_id ? byId[draft.assignee_id] : null;
  const reviewer = draft.reviewer_id ? byId[draft.reviewer_id] : null;
  const canReview = can("drafts.review");

  const act = async (kind, fn, message) => {
    setBusy(kind);
    setError(null);
    try {
      const res = await fn();
      notifications.show({ color: kind === "reject" ? "gray" : "teal", message: typeof message === "function" ? message(res) : message });
      onDecided();
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <Group justify="space-between" mb="md" wrap="wrap" gap="xs">
        <Group gap={6} c="dimmed">
          <IconCalendarEvent size={16} />
          <Text size="sm">
            <Text span component={Link} to={`/meetings/${draft.meeting_id}`} inherit c="dimmed" td="underline">
              «{draft.meeting_title}»
            </Text>{" "}
            · {dayMonth(draft.meeting_date)}
          </Text>
        </Group>
        <Badge variant="light" color="violet" leftSection={<IconSparkles size={12} />}>Предложил ИИ · ждёт решения</Badge>
      </Group>
      {error ? <Box mb="md"><Banner kind="error">{error}</Banner></Box> : null}

      {editing ? (
        <EditForm
          draft={draft}
          busy={busy === "edit"}
          onCancel={() => setEditing(false)}
          onSave={async (patch) => {
            if (await act("edit", () => api.editDraft(draft.id, patch), "Изменения сохранены")) setEditing(false);
          }}
        />
      ) : (
        <Stack gap="md">
          <div>
            <Title order={3}>{draft.title}</Title>
            {draft.description ? <Text c="dimmed" mt={6}>{draft.description}</Text> : null}
          </div>
          {draft.acceptance_criteria.length ? (
            <Field label="Критерии готовности">
              <List size="sm" spacing={4}>
                {draft.acceptance_criteria.map((c) => <List.Item key={c}>{c}</List.Item>)}
              </List>
            </Field>
          ) : null}
          <Group gap="xl">
            <Field label="Исполнитель">
              {assignee ? (
                <Group gap="xs"><UserAvatar user={assignee} size="sm" /><Text size="sm" fw={500}>{assignee.name}</Text></Group>
              ) : (
                <Text size="sm" c="dimmed">не указан</Text>
              )}
            </Field>
            <Field label="Срок">
              <Text size="sm" fw={draft.due_text ? 500 : 400} c={draft.due_text ? undefined : "dimmed"}>{draft.due_text ? `${draft.due_text}${draft.due_date ? ` · ${draft.due_date.split("-").reverse().join(".")}` : ""}` : "не указан"}</Text>
            </Field>
          </Group>
          {draft.source_quote ? <div className="quote">Из встречи — «{draft.source_quote}»</div> : null}
          {draft.meeting_skipped_note ? <Text size="sm" c="dimmed" fs="italic">{draft.meeting_skipped_note}</Text> : null}
          <Text size="xs" c="dimmed">
            {reviewer ? `Проверяет ${reviewer.name}. ` : ""}Пока решение не принято, задачи нет ни в бэклоге, ни на доске.
          </Text>
          {canReview ? (
            <Group>
              <Button
                leftSection={<IconCheck size={16} />}
                loading={busy === "approve"}
                disabled={Boolean(busy)}
                onClick={() => act("approve", () => api.approveDraft(draft.id), (t) => `Задача ${t.key} добавлена в бэклог`)}
              >
                Принять
              </Button>
              <Button variant="default" leftSection={<IconPencil size={16} />} disabled={Boolean(busy)} onClick={() => setEditing(true)}>
                Изменить
              </Button>
              <Button
                variant="subtle"
                color="red"
                leftSection={<IconX size={16} />}
                loading={busy === "reject"}
                disabled={Boolean(busy)}
                onClick={() => act("reject", () => api.rejectDraft(draft.id), "Предложение отклонено")}
              >
                Отклонить
              </Button>
            </Group>
          ) : (
            <Banner kind="info">Принимать и отклонять предложения может руководитель или администратор.</Banner>
          )}
        </Stack>
      )}
    </Card>
  );
}

export default function ReviewPage() {
  const { data: drafts, error, reload } = useLoad(() => api.drafts("pending"), []);

  return (
    <Page title="Проверка предложений ИИ" sub="Человек принимает, меняет или отклоняет задачу до бэклога">
      {error ? <Banner kind="error">{error.message}</Banner> : null}
      {drafts && !drafts.length ? (
        <Card>
          <EmptyState icon={IconChecklist} title="Очередь пуста">
            Новые предложения появятся здесь после обработки встречи.{" "}
            <Text span component={Link} to="/call" c="indigo" inherit>Начать звонок</Text> или{" "}
            <Text span component={Link} to="/meetings" c="indigo" inherit>открыть встречи</Text>.
          </EmptyState>
        </Card>
      ) : null}
      <Stack maw={820}>
        {drafts?.map((d) => (
          <DraftCard key={d.id} draft={d} onDecided={() => reload(true)} />
        ))}
      </Stack>
    </Page>
  );
}
