// The event names the pipeline writes (history.py), in words a customer reads.
const EVENT_LABELS: Record<string, string> = {
  registered: 'Registered',
  removed_from_register: 'Removed from register',
  deregistered: 'Deregistered',
  name_changed: 'Name changed',
  legal_form_changed: 'Legal form changed',
  address_changed: 'Address changed',
  description_changed: 'Business description changed',
  proceeding_started: 'Proceedings started',
  proceeding_ended: 'Proceedings ended',
}

export const eventLabel = (e: string) => EVENT_LABELS[e] ?? e
