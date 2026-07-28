from app import app
from quote_sampler import run_quote_sampler_worker


def main():
    run_quote_sampler_worker(app)


if __name__ == "__main__":
    main()