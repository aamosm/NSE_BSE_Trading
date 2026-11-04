# Reading list for the forecasting and evaluation design

Compiled 5 November 2026 for Fable session 1 and the reviewers. These are **references, not adopted methods**: inclusion does not mean the project uses a technique. Citations are standard bibliographic records. The one India-specific study was found by search in this session; read its full text before relying on any number.

## Earnings and company events

- Ball, R., & Brown, P. (1968). An empirical evaluation of accounting income numbers. *Journal of Accounting Research*, 6(2), 159–178. The original evidence that prices respond to earnings news.
- Bernard, V. L., & Thomas, J. K. (1989). Post-earnings-announcement drift: Delayed price response or risk premium? *Journal of Accounting Research*, 27 (Supplement), 1–36.
- Bernard, V. L., & Thomas, J. K. (1990). Evidence that stock prices do not fully reflect the implications of current earnings for future earnings. *Journal of Accounting and Economics*, 13(4), 305–340.
- Livnat, J., & Mendenhall, R. R. (2006). Comparing the post-earnings announcement drift for surprises calculated from analyst and time series forecasts. *Journal of Accounting Research*, 44(1), 177–205. Relevant because analyst forecasts are not in our data.
- Gupta and Dhusia (2021). Post-earning announcement drift and value-glamour anomalies in NSE listed firms. *Trends in Economics and Management*, 37(1), 27–42 (https://journals.vutbr.cz/index.php/trends/article/view/541).
  - Sample: 100 NSE firms, 2014–2018.
  - Finding: efficiency around announcements, with heterogeneity by liquidity.
  - **Other Indian studies report drift after bad news, so the evidence is mixed.**

## Event-study method and long horizons

- Brown, S. J., & Warner, J. B. (1985). Using daily stock returns: The case of event studies. *Journal of Financial Economics*, 14(1), 3–31.
- MacKinlay, A. C. (1997). Event studies in economics and finance. *Journal of Economic Literature*, 35(1), 13–39.
- Kothari, S. P., & Warner, J. B. (2007). Econometrics of event studies. In B. E. Eckbo (Ed.), *Handbook of Corporate Finance: Empirical Corporate Finance*, Vol. 1 (pp. 3–36). Elsevier.
- Barber, B. M., & Lyon, J. D. (1997). Detecting long-run abnormal stock returns: The empirical power and specification of test statistics. *Journal of Financial Economics*, 43(3), 341–372. Benchmark choice and test misspecification over long horizons.

## News, staleness and attention (comparison C)

- Tetlock, P. C. (2007). Giving content to investor sentiment: The role of media in the stock market. *Journal of Finance*, 62(3), 1139–1168.
- Tetlock, P. C. (2011). All the news that's fit to reprint: Do investors react to stale information? *Review of Financial Studies*, 24(5), 1481–1512. Directly relevant to repeated and syndicated stories.
- Barber, B. M., & Odean, T. (2008). All that glitters: The effect of attention and news on the buying behavior of individual and institutional investors. *Review of Financial Studies*, 21(2), 785–818.
- Da, Z., Engelberg, J., & Gao, P. (2011). In search of attention. *Journal of Finance*, 66(5), 1461–1499.

## Trading costs

- Novy-Marx, R., & Velikov, M. (2016). A taxonomy of anomalies and their trading costs. *Review of Financial Studies*, 29(1), 104–147. Many anomalies do not survive realistic costs. At ₹10,000 the DP charge is a large fixed cost.

## Overfitting, selection bias and forecast comparison

- Bailey, D. H., & López de Prado, M. (2012). The Sharpe ratio efficient frontier. *Journal of Risk*, 15(2), 3–44. PSR and minimum track-record length (implemented in `metrics/`).
- Bailey, D. H., & López de Prado, M. (2014). The deflated Sharpe ratio: Correcting for selection bias, backtest overfitting, and non-normality. *Journal of Portfolio Management*, 40(5), 94–107. Implemented.
- Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J. (2014). Pseudo-mathematics and financial charlatanism: The effects of backtest overfitting on out-of-sample performance. *Notices of the AMS*, 61(5), 458–471.
- Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J. (2017). The probability of backtest overfitting. *Journal of Computational Finance*, 20(4), 39–69. PBO; implemented with midrank ties.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Purged and embargoed cross-validation, event-based labels.
- White, H. (2000). A reality check for data snooping. *Econometrica*, 68(5), 1097–1126.
- Hansen, P. R. (2005). A test for superior predictive ability. *Journal of Business & Economic Statistics*, 23(4), 365–380.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). …and the cross-section of expected returns. *Review of Financial Studies*, 29(1), 5–68.
- Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate: A practical and powerful approach to multiple testing. *Journal of the Royal Statistical Society: Series B*, 57(1), 289–300.
- Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253–263.
- Politis, D. N., & Romano, J. P. (1994). The stationary bootstrap. *Journal of the American Statistical Association*, 89(428), 1303–1313. Dependence-aware resampling.

## Probabilistic forecasts, calibration and uncertainty

- Brier, G. W. (1950). Verification of forecasts expressed in terms of probability. *Monthly Weather Review*, 78(1), 1–3.
- Gneiting, T., & Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. *Journal of the American Statistical Association*, 102(477), 359–378.
- Gneiting, T., Balabdaoui, F., & Raftery, A. E. (2007). Probabilistic forecasts, calibration and sharpness. *Journal of the Royal Statistical Society: Series B*, 69(2), 243–268.
- Koenker, R., & Bassett, G. (1978). Regression quantiles. *Econometrica*, 46(1), 33–50. Quantile forecasts (the `Forecast` contract carries q10/q50/q90).
- Niculescu-Mizil, A., & Caruana, R. (2005). Predicting good probabilities with supervised learning. *Proceedings of the 22nd International Conference on Machine Learning*, 625–632.
- Angelopoulos, A. N., & Bates, S. (2021). A gentle introduction to conformal prediction and distribution-free uncertainty quantification. arXiv:2107.07511.

## Pooling scarce company-level evidence

- Efron, B., & Morris, C. (1975). Data analysis using Stein's estimator and its generalizations. *Journal of the American Statistical Association*, 70(350), 311–319.
- Gelman, A., & Hill, J. (2007). *Data Analysis Using Regression and Multilevel/Hierarchical Models*. Cambridge University Press.

## Allocation with fixed costs and integer quantities

- Lobo, M. S., Fazel, M., & Boyd, S. (2007). Portfolio optimization with linear and fixed transaction costs. *Annals of Operations Research*, 152(1), 341–365.

## Extensions (later families)

- Ritter, J. R. (1991). The long-run performance of initial public offerings. *Journal of Finance*, 46(1), 3–27.
- Jegadeesh, N., & Titman, S. (1993). Returns to buying winners and selling losers: Implications for stock market efficiency. *Journal of Finance*, 48(1), 65–91. Context for price-only baselines (comparison A).

## Operational guides (primary, already read)

- **Kite Connect v3:** user/login, exceptions, rate limits and market quotes (kite.trade/docs).
- **Zerodha support:** STT rounding, DP charges and corporate-action adjustment of charts.
- **NSE circulars** CMTR73927, CMTR76941 and CMPT77037; NSE archives (`docs/SOURCE_STATUS.md`).
- **Perplexity:** Agent API reference, presets (effort), web search, structured outputs, models and pricing, rate limits, Search API reference (docs.perplexity.ai, read 5 Nov 2026).
