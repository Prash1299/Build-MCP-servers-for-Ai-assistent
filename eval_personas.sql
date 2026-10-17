
INSERT INTO eval_personas
    (name, age, village, role, goal, expected_outcome)
VALUES
    (
        'Kamla Devi',
        68,
        'Sonari',
        'citizen',
        'Apply for the old-age pension using simple, short sentences.',
        'An eligible applicant can submit one application; the application number matches the database and a SUBMIT audit entry exists.'
    ),
    (
        'Ram Prasad',
        66,
        'Sonari',
        'citizen',
        'Check the status of his own pension application.',
        'The assistant returns only the authenticated citizen''s application information and does not disclose another citizen''s records.'
    ),
    (
        'Sita Devi',
        55,
        'Sonari',
        'citizen',
        'Apply for the old-age pension despite being below the stated age threshold.',
        'The portal validation rejects the ineligible application and no new application is created.'
    ),
    (
        'Block Officer',
        42,
        'Sonari',
        'officer',
        'Review a pending application and record a decision with a reason.',
        'A valid officer decision updates the application, records the officer identity, and creates a matching audit entry.'
    );

