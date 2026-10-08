# RB-005 · Kafka consumer lag growing
Services: kafka-events
Severity hint: SEV3, SEV2 if order events are delayed by more than 15 minutes
Owner: Streaming Platform

## Symptoms
- Consumer lag keeps rising on the `orders` or `payments` topics.
- Downstream services show stale data, such as order status not updating.
- Consumers log `Offset commit failed` or frequent rebalances.

## Diagnosis
1. [low] Check lag per partition: `kafka-consumer-groups --bootstrap-server <broker>:9092 --describe --group <group>`
2. [low] Check for rebalance storms in consumer logs: `kubectl logs deployment/<consumer> -n <namespace> | grep -i rebalance`
3. [low] Check whether one partition is hot because of key skew.
4. [low] Check broker health and under-replicated partitions: `kafka-topics --bootstrap-server <broker>:9092 --describe --under-replicated-partitions`

## Remediation
1. [medium] Scale the consumer deployment up to the partition count: `kubectl scale deployment/<consumer> -n <namespace> --replicas=<n>`
2. [medium] If rebalances are caused by slow processing, raise `max.poll.interval.ms` and redeploy.
3. [high] Reset the group offset to skip poison messages, only with the service owner's agreement: `kafka-consumer-groups --bootstrap-server <broker>:9092 --group <group> --reset-offsets --to-datetime <timestamp> --topic <topic> --execute`

## Rollback
- Scale the consumer back to its normal replica count once lag is under 1,000 messages.

## Escalation
Streaming Platform on-call. Offset resets need approval from the owning service team.
