import { expect } from '@jest/globals';
import { diagnostics } from '../src/common/diagnostics';

describe('Diagnostics tests', () => {
  it('should handle health output shape', () => {
    const healthOutput = diagnostics.healthOutput();
    expect(healthOutput).toHaveProperty('status');
    expect(healthOutput).toHaveProperty('message');
    expect(healthOutput).toHaveProperty('timestamp');
  });

  it('should handle failure handling', async () => {
    const failureOutput = diagnostics.failureOutput();
    expect(failureOutput).toHaveProperty('status');
    expect(failureOutput).toHaveProperty('message');
    expect(failureOutput).toHaveProperty('timestamp');
    expect(failureOutput).toHaveProperty('details');
  });
});
